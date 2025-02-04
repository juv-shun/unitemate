import time
import math
import boto3
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr

dynamodb = boto3.resource('dynamodb')
queue_table = dynamodb.Table('QueueTable')    # キュー情報テーブル
user_table = dynamodb.Table('UserTable')        # ユーザー情報テーブル
matches_table = dynamodb.Table('MatchesTable')  # マッチ結果保存テーブル（例）

# 20秒毎に呼ばれるマッチメイク処理のエントリポイント
def lambda_handler(event, context):
    """
    1. QueueTableから"waiting"状態のプレイヤーを取得し、
       ユーザーごとの最新レートと許容レンジを計算する。
    2. プレイヤーをレートの高い順にソートし、上からグループ形成の試行を行う。
    3. 10人グループが形成できたらマッチ成立とし、グループに入らなかったプレイヤーは
       次回のためにrange_spread_countをインクリメントする。
    """
    waiting_users = get_waiting_users(namespace="default")
    
    # 各プレイヤーの最新レートと許容レンジを計算
    players = []
    for user in waiting_users:
        user_id = user["user_id"]
        # ★ 将来拡張: blocking, role を利用した処理をここに挿入可能
        rating = get_user_rating(user_id)
        spread_count = user["range_spread_count"]
        spread_speed = user["range_spread_speed"]
        
        if spread_count >= 5:
            min_rating = -math.inf
            max_rating = math.inf
        else:
            base = 50 + spread_speed * spread_count
            min_rating = rating - base
            max_rating = rating + base
        
        players.append({
            "user_id": user_id,
            "rating": rating,
            "min_rating": min_rating,
            "max_rating": max_rating,
            "range_spread_speed": spread_speed,
            "range_spread_count": spread_count,
            "inqueued_unixtime": user["inqueued_unixtime"]
        })
    
    # 降順（高い順）にソート
    players.sort(key=lambda x: x["rating"], reverse=True)
    
    # グループ形成：できるだけ多くの10人グループを形成する
    matched_groups = form_matches_from_pool(players)
    
    if matched_groups:
        all_matched_ids = []
        for group in matched_groups:
            finalize_match(group)
            all_matched_ids.extend([p["user_id"] for p in group])
        # 残りのプレイヤーは、今回マッチできなかったのでrange_spread_countをインクリメント
        matched_set = set(all_matched_ids)
        for p in players:
            if p["user_id"] not in matched_set:
                increment_range_spread_count(p["user_id"])
        return {
            "statusCode": 200,
            "body": f"Matched {len(matched_groups)} groups: {all_matched_ids}"
        }
    else:
        # 1件もマッチ成立しなかった場合は、全員のrange_spread_countをインクリメント
        for p in players:
            increment_range_spread_count(p["user_id"])
        return {
            "statusCode": 200,
            "body": "No matches found. Incremented range_spread_count for all waiting players."
        }

def get_waiting_users(namespace="default"):
    """DynamoDBからnamespaceおよびstatus="waiting"のプレイヤーを取得する（簡易版）"""
    resp = queue_table.scan(
        FilterExpression=Attr("status").eq("waiting") & Attr("namespace").eq(namespace)
    )
    return resp.get("Items", [])

def get_user_rating(user_id):
    """UserTableから最新のレートを取得する"""
    resp = user_table.get_item(Key={"user_id": user_id})
    if "Item" in resp:
        return resp["Item"].get("rating", 1500)
    return 1500

def form_matches_from_pool(pool):
    """
    pool: 降順（レートが高い順）にソートされたプレイヤーのリスト
    戻り値: マッチ成立したグループのリスト（各グループは10人のリスト）
    
    各アンカーからグループ形成を試み、グループ形成が成功したら
    そのメンバーをpoolから除外して、以降は未マッチのプレイヤーのみで再試行する。
    """
    matched_groups = []
    used_ids = set()  # すでにマッチに採用されたプレイヤーのID
    
    # pool内の各プレイヤーについて、未マッチならアンカーとしてグループ形成を試行
    for player in pool:
        if player["user_id"] in used_ids:
            continue
        group = try_form_group(player, pool, used_ids)
        if group and len(group) == 10:
            matched_groups.append(group)
            # マッチに採用されたプレイヤーのIDを記録
            for p in group:
                used_ids.add(p["user_id"])
    return matched_groups

def try_form_group(anchor, pool, used_ids):
    """
    アンカーからグループ形成をグリーディに試みる。
    ・初期グループは [anchor] とし、交差区間 I を anchor の許容レンジで初期化する。
    ・pool内（かつ未採用のプレイヤー）を降順で走査し、各候補について
      新たな交差区間 I' = intersection(I, candidateのレンジ) を計算する。
      もし I' が空でなければ、候補をグループに追加し、I を I' に更新する。
    ・グループのサイズが10になれば成功とする。
    戻り値: 形成されたグループ（サイズ10のリスト）または None
    """
    group = [anchor]
    # 現在の交差区間 I = [current_min, current_max]
    current_min = anchor["min_rating"]
    current_max = anchor["max_rating"]
    
    # pool内で、かつ既にマッチに採用されていないプレイヤーを対象に（アンカーを除く）
    # ※すでに採用済みのものは除外
    for candidate in pool:
        if candidate["user_id"] in used_ids:
            continue
        if candidate["user_id"] == anchor["user_id"]:
            continue
        # 新たな交差区間を計算
        new_min = max(current_min, candidate["min_rating"])
        new_max = min(current_max, candidate["max_rating"])
        if new_min <= new_max:
            # candidateをグループに追加できる
            group.append(candidate)
            current_min, current_max = new_min, new_max
            if len(group) == 10:
                return group
    # 10人に満たなければ失敗
    return None

def finalize_match(group):
    """
    マッチ成立した10人のグループに対して、QueueTableのstatus更新およびMatchesTableへの記録を行う。
    将来的には、roleやblockingを考慮したチーム分割情報を保存する処理を追加可能。
    """
    user_ids = [p["user_id"] for p in group]
    # QueueTable内の各プレイヤーのstatusを"matched"に更新
    for uid in user_ids:
        queue_table.update_item(
            Key={"namespace": "default", "user_id": uid},
            UpdateExpression="SET #st = :matched",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":matched": "matched"}
        )
    # MatchesTableへレコード作成（match_idはタイムスタンプ例）
    match_id = str(int(time.time() * 1000))
    matches_table.put_item(
        Item={
            "match_id": match_id,
            "user_ids": user_ids,
            "timestamp": int(time.time())
            # ★ 将来拡張: ここでチーム分割情報 (teamA, teamB) を付与する
        }
    )

def increment_range_spread_count(user_id):
    """マッチに入らなかったプレイヤーのrange_spread_countをインクリメントする"""
    queue_table.update_item(
        Key={"namespace": "default", "user_id": user_id},
        ConditionExpression=Attr("status").eq("waiting"),
        UpdateExpression="SET #c = #c + :inc",
        ExpressionAttributeNames={"#c": "range_spread_count"},
        ExpressionAttributeValues={":inc": 1}
    )
