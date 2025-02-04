import time
import math
import boto3
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr

dynamodb = boto3.resource('dynamodb')
queue_table = dynamodb.Table('QueueTable')   # キュー情報テーブル
user_table = dynamodb.Table('UserTable')     # ユーザー情報テーブル
matches_table = dynamodb.Table('MatchesTable')  # マッチ結果保存テーブル(例: 必要に応じて)

# ★ 20秒ごとにこの関数が呼ばれる想定
def lambda_handler(event, context):
    """
    20秒に一度呼ばれるマッチメイク関数の例。
    1) QueueTable から "waiting" 状態のユーザーを取得
    2) 各ユーザーの最新レートをUserTableから取得
    3) 5vs5が成立するグループがあればマッチ確定
    4) マッチに失敗したユーザーは range_spread_count をインクリメント
    """
    # 1) 待機中のユーザーをまとめて取得 (namespace="default" を例に)
    waiting_users = get_waiting_users(namespace="default")

    # 2) 各ユーザーのレートを取得し、レート範囲(min, max)を計算
    #    role, blocking は無視するが、将来のための拡張ポイントとしてコメントを入れる
    users_with_range = []
    for user in waiting_users:
        user_id = user["user_id"]
        
        # --- 将来: blockingを考慮して同じマッチに入れないユーザーをフィルタする ---
        # blocking_info = user["blocking"]  # 今回は使わない
        
        # --- 将来: roleを考慮してチーム構成のロジックを強化する ---
        # role_info = user["role"]  # 今回は使わない
        
        # UserTable からユーザーの最新レートを取得
        rating = get_user_rating(user_id)
        
        # range_spread_count が 5以上なら無限範囲とする
        spread_count = user["range_spread_count"]
        spread_speed = user["range_spread_speed"]
        
        if spread_count >= 5:
            min_rating = -math.inf
            max_rating = math.inf
        else:
            # ベース = 50
            # 広がり = spread_speed * spread_count
            # 例:  range_spread_speed=20, range_spread_count=1 → ±(50+20*1)=±70
            base_range = 50 + spread_speed * spread_count
            min_rating = rating - base_range
            max_rating = rating + base_range
        
        users_with_range.append({
            "user_id": user_id,
            "rating": rating,
            "min_rating": min_rating,
            "max_rating": max_rating,
            "range_spread_speed": spread_speed,
            "range_spread_count": spread_count,
            "inqueued_unixtime": user["inqueued_unixtime"]
        })
    
    # 3) 5vs5のマッチングロジック
    matched_group = find_5v5_match(users_with_range)
    
    if matched_group:
        # マッチが成立した10人を処理
        finalize_match(matched_group)
        
        # マッチに含まれなかったユーザー: range_spread_countをインクリメント
        # (すでに matched になったユーザーは除外)
        matched_user_ids = {u["user_id"] for u in matched_group}
        for user in users_with_range:
            if user["user_id"] not in matched_user_ids:
                increment_range_spread_count(user["user_id"])
        
        return {
            "statusCode": 200,
            "body": f"Match success: {matched_user_ids}"
        }
    else:
        # 10人揃わず不成立 → 全員 range_spread_countをインクリメント
        for user in users_with_range:
            increment_range_spread_count(user["user_id"])
        
        return {
            "statusCode": 200,
            "body": "No match found. All waiting users incremented range_spread_count."
        }


def get_waiting_users(namespace="default"):
    """
    DynamoDBからstatus="waiting" かつ指定のnamespaceのユーザーを取得。
    実装例としてscanを使うが、本番ではGSIやPartitionKey検索で最適化を検討。
    """
    resp = queue_table.scan(
        FilterExpression=Attr("status").eq("waiting") & Attr("namespace").eq(namespace)
    )
    items = resp.get("Items", [])
    return items


def get_user_rating(user_id):
    """
    UserTableからユーザーの最新レートを取得する。
    """
    resp = user_table.get_item(
        Key={"user_id": user_id}
    )
    if "Item" in resp:
        return resp["Item"].get("rating", 1500)  # レートが無ければ仮に1500とする
    # 万が一見つからない場合は、デフォルト値orエラー等の処理
    return 1500


def find_5v5_match(users_with_range):
    """
    今回は「ロールやブロック無視で、レート範囲の一致のみで 10人を探す」
    
    簡易アルゴリズム:
      1) ratingでソート
      2) 連続する10人を取り出し、それら全員が互いのmin_rating ~ max_ratingに収まるかチェック
      3) 最初に見つかった10人を返す (複数候補があれば一番早いインデックスを採用)
    """
    if len(users_with_range) < 10:
        return None
    
    # ratingでソート
    sorted_users = sorted(users_with_range, key=lambda x: x["rating"])
    n = len(sorted_users)
    
    for start_idx in range(n - 9):
        group_10 = sorted_users[start_idx:start_idx+10]
        
        # 全員の rating の最小値/最大値
        group_min = min(u["rating"] for u in group_10)
        group_max = max(u["rating"] for u in group_10)
        
        # 互いの range を満たしているかチェック
        # 例: ユーザー u の (min_rating <= group_max) and (max_rating >= group_min)
        # が全員成立すれば OK
        all_ok = True
        for u in group_10:
            if u["max_rating"] < group_max or u["min_rating"] > group_min:
                all_ok = False
                break
        
        if all_ok:
            # 5vs5 が組める → 実際にチーム分けなどは今回は単純に
            # "適当に前から5人, 後ろ5人" とする or "ロールを見て分ける(将来拡張)"
            # 今はロール無視のため適当にA,B振り分けするとして、group_10自体をreturn
            return group_10
    return None


def finalize_match(matched_group):
    """
    マッチが成立した 10人を 'matched' に更新し、MatchesTableなどに記録する。
    ロール, blockingを考慮したチーム振り分けは将来拡張のポイントにする。
    """
    user_ids = [u["user_id"] for u in matched_group]
    
    # QueueTableを更新
    for user_id in user_ids:
        queue_table.update_item(
            Key={
                "namespace": "default",
                "user_id": user_id
            },
            UpdateExpression="SET #st = :matched",
            ExpressionAttributeNames={
                "#st": "status"
            },
            ExpressionAttributeValues={
                ":matched": "matched"
            }
        )
    
    # MatchesTable にレコードを作る (必要ならマッチIDなど作成)
    match_id = str(int(time.time() * 1000))  # 単純にタイムスタンプをIDにする例
    matches_table.put_item(
        Item={
            "match_id": match_id,
            "user_ids": user_ids,
            "timestamp": int(time.time()),
            # 将来: ロール/チーム情報をここに付与する
        }
    )


def increment_range_spread_count(user_id):
    """
    マッチに失敗したユーザーのrange_spread_countを +1 する。
    statusが既にwaitingでない場合は更新しないように注意する。
    """
    # Atomicな更新のために condition などをつけてもいいが、今回はシンプルに行う
    queue_table.update_item(
        Key={
            "namespace": "default",
            "user_id": user_id
        },
        ConditionExpression=Attr("status").eq("waiting"),
        UpdateExpression="SET #c = #c + :inc",
        ExpressionAttributeNames={"#c": "range_spread_count"},
        ExpressionAttributeValues={":inc": 1}
    )
