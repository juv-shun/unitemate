import os
import random
from datetime import datetime, timedelta, timezone
import json
import time

from requests.exceptions import RequestException
import boto3
import requests
from boto3.dynamodb.conditions import Attr, Key

from .ws_helper import broadcast_last_queue_info
import asyncio
import math
import aiohttp

JST = timezone(timedelta(hours=+9), "JST")

dynamodb = boto3.resource("dynamodb")
queue_table = dynamodb.Table(os.environ["MATCH_QUEUE"])
matches_table = dynamodb.Table(os.environ["MATCH_TABLE"])
user_table = dynamodb.Table(os.environ["USER_TABLE"])
connection_table = dynamodb.Table(os.environ["CONNECTION_TABLE"])


def update_bubble_queue_via_ws(queue_count):
    try:
        connection_resp = connection_table.scan(ProjectionExpression="connection_id")
        connection_ids = [
            item["connection_id"] for item in connection_resp.get("Items", [])
        ]
        asyncio.run(broadcast_last_queue_info(queue_count, connection_ids))
    except Exception as e:
        pass

# TODO webhookURLはパラメータに移行したい
WEBHOOK_URL = "https://discord.com/api/webhooks/1185019044391305226/NbOT6mnrZNHS61T5ro7iu2smxyhhSPH_tecLnWmZ91kup96-mtpdcGwvvo3kjmyzR96_"

# 20秒毎に呼ばれるマッチメイク処理のエントリポイント
def handle(event, context):
    """
    1. QueueTableから"waiting"状態のプレイヤーを取得し、
       ユーザーごとの最新レートと許容レンジを計算する。
    2. プレイヤーをレートの高い順にソートし、上からグループ形成の試行を行う。
    3. 10人グループが形成できたらマッチ成立とし、グループに入らなかったプレイヤーは
       次回のためにrange_spread_countをインクリメントする。
    """
    waiting_users = get_waiting_users(queue_table)

    if len(waiting_users) < 10:
        for p in waiting_users:
            increment_range_spread_count(p["user_id"])
        return {
            "statusCode": 200,
            "body": "No matches found. Incremented range_spread_count for all waiting players."
        }
    
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
            "inqueued_unixtime": user["inqueued_unixtime"],
            "discord_id": user["discord_id"] # キュー情報に含む
        })
    
    # 降順（高い順）にソート
    players.sort(key=lambda x: x["rating"], reverse=True)
    
    # グループ形成：できるだけ多くの10人グループを形成する
    matched_groups = form_matches_from_pool(players)
    
    if matched_groups:
        # METAアイテムから最新のマッチIDを取得（なければ初期値0）  
        meta_item = queue_table.get_item(Key={"namespace": "default", "user_id": "#META#"}).get("Item")
        match_id_base = int(meta_item.get("LatestMatchID", 0))
        unused_vc = meta_item.get("UnusedVC", list(range(1, 100, 2)))
        
        # 各グループに対して連番のマッチIDを割り当て、マッチレコードを作成＆通知
        for i, group in enumerate(matched_groups):
            current_match_id = match_id_base + i + 1
            # VCの割り当て：UnusedVCから先頭の奇数をpop（チームAのVC）、チームBはその値+1
            if len(unused_vc) < 1:
                raise Exception("UnusedVCが不足しています。")
            vc_a = unused_vc.pop(0)
            vc_b = vc_a + 1
            finalize_match(group, current_match_id, vc_a, vc_b)
        
         # METAアイテムの更新：LatestMatchID と UnusedVC を１回の update_item で更新
        new_match_id_base = match_id_base + len(matched_groups)
        queue_table.update_item(
            Key={"namespace": "default", "user_id": "#META#"},
            UpdateExpression="SET LatestMatchID = :newID, UnusedVC = :vcList",
            ExpressionAttributeValues={":newID": new_match_id_base, ":vcList": unused_vc}
        )
        
        # 形成できなかったプレイヤーはrate_spread_countをインクリメント
        used_ids = {p["user_id"] for group in matched_groups for p in group}
        for p in players:
            if p["user_id"] not in used_ids:
                increment_range_spread_count(p["user_id"])
        
        return {
            "statusCode": 200,
            "body": f"Matched {len(matched_groups)} groups. Match IDs assigned from {match_id_base+1} to {new_match_id_base}."
        }
    else:
        # 1件もマッチ成立しなかった場合は、全員のrange_spread_countをインクリメント
        for p in players:
            increment_range_spread_count(p["user_id"])
        return {
            "statusCode": 200,
            "body": "No matches found. Incremented range_spread_count for all waiting players."
        }

def get_waiting_users(queue):
    """マッチキューからマッチング待ちのユーザを取得"""
    response = queue.query(
        IndexName="rate_index",
        KeyConditionExpression=Key("namespace").eq("default"),
        ScanIndexForward=False,
        ProjectionExpression="user_id, rate, blocking, role, rate_spread_speed, rate_spread_count, discord_id",
    )
    return response["Items"]

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


def finalize_match(group, match_id, vc_a, vc_b):
    """
    マッチ成立した10人グループに対して：
      1. QueueTableから各プレイヤーのエントリを削除する。
      2. MatchesTableへマッチレコードを作成（match_idは引数で与えられる連番）。
      3. METAアイテムからUnusedVC（奇数のみのリスト）を取得し、先頭の奇数をpopし、
         チームAのVC番号とし、チームBのVC番号はそのVC+1とする。METAアイテムは更新する。
      4. 10人グループはレート順にペア化し、各ペア内でランダムに割り当ててチームA・Bを決定する。
      5. notify_discord()を呼び出してDiscordへマッチ通知を送信する。
    """
    user_ids = [p["user_id"] for p in group]
    
    # ① QueueTableから各プレイヤーのエントリを削除
    for uid in user_ids:
        queue_table.delete_item(Key={"namespace": "default", "user_id": uid})

    update_assigned_match_ids(user_ids, match_id)
    
    
    # ④ チーム分け：グループは既にレート順になっている前提で、隣り合わせのペアを作り、各ペア内でランダムに割り振る
    pairs = []
    for i in range(0, len(group), 2):
        pair = group[i:i+2]
        if len(pair) < 2:
            continue
        random.shuffle(pair)
        pairs.append(pair)
    team_a_players = [pair[0] for pair in pairs]
    team_b_players = [pair[1] for pair in pairs]
    team_a_discord = [p.get("discord_id", "") for p in team_a_players]
    team_b_discord = [p.get("discord_id", "") for p in team_b_players]

    # ② MatchesTableへマッチレコードを作成
    matches_table.put_item(
        Item={
            "match_id": int(match_id),  # match_idはint型
            "team_A": [[p["user_id"], int(p["rate"])] for p in team_a_players],
            "team_B": [[p["user_id"], int(p["rate"])] for p in team_b_players],
            "matched_unix_time": int(time.time()),
            "status": "matched",
            "user_reports": [],
            "penalty_player": [],
            "judge_timeout_count": 0,
            "vc_A": int(vc_a),
            "vc_B": int(vc_a + 1)
        }
    )

    
    # ⑤ Discordへ通知送信
    asyncio.run(notify_discord(match_id, vc_a, vc_b, team_a_discord, team_b_discord))



def increment_range_spread_count(user_id):
    """マッチに入らなかったプレイヤーのrange_spread_countをインクリメントする"""
    queue_table.update_item(
        Key={"namespace": "default", "user_id": user_id},
        ConditionExpression=Attr("status").eq("waiting"),
        UpdateExpression="SET #c = #c + :inc",
        ExpressionAttributeNames={"#c": "range_spread_count"},
        ExpressionAttributeValues={":inc": 1}
    )

# 各プレイヤーの assigned_match_id を新しい match_id に更新する処理
def update_assigned_match_ids(user_ids, match_id):
    for uid in user_ids:
        user_table.update_item(
            Key={"user_id": uid},
            UpdateExpression="SET assigned_match_id = :m",
            ExpressionAttributeValues={":m": match_id}
        )

async def notify_discord(match_id, vc_a, vc_b, team_a, team_b):
    """
    DiscordのWebhookを用いてマッチ通知を送信する関数。
    """
    # プレイヤーIDリストをスペース区切りで連結
    team_a_str = " ".join(team_a)
    team_b_str = " ".join(team_b)
    
    content = (
        f"**VC有りバトルでマッチしました**\r"
        f"先攻チーム VC{vc_a}\r {team_a_str}\r\r"
        f"後攻チーム VC{vc_b}\r {team_b_str}\r\r"
        f"*サイト上のタイマー以内にロビーに集合してください。集まらない場合、試合を無効にしてください。*\r"
        f"ID: ||{match_id}||\r"
    )
    
    payload = {"content": content}
    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(WEBHOOK_URL, json=payload, headers=headers) as response:
            if response.status == 204:
                print("Discord通知送信成功")
            else:
                text = await response.text()
                print(f"Discord通知送信失敗: {response.status}")
                print("レスポンス:", text)