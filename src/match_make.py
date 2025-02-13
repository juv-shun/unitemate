import os
import random
from datetime import datetime, timedelta, timezone
import json
import time

from requests.exceptions import RequestException
import boto3
import requests
from boto3.dynamodb.conditions import Attr, Key

from .ws_helper import broadcast_queue_count
import asyncio
import math
import aiohttp
JST = timezone(timedelta(hours=+9), "JST")

dynamodb = boto3.resource("dynamodb")
queue_table = dynamodb.Table(os.environ["MATCH_QUEUE"])
matches_table = dynamodb.Table(os.environ["MATCH_TABLE"])
user_table = dynamodb.Table(os.environ["USER_TABLE"])
connection_table = dynamodb.Table(os.environ["CONNECTION_TABLE"])


# TODO webhookURLはパラメータに移行したい
WEBHOOK_URL = "https://discord.com/api/webhooks/1185019044391305226/NbOT6mnrZNHS61T5ro7iu2smxyhhSPH_tecLnWmZ91kup96-mtpdcGwvvo3kjmyzR96_"
BUBBLE_ASSIGN_MATCH_URL = os.environ["BUBBLE_ASSIGN_MATCH_URL"]
BUBBLE_API_KEY = "da60b1aedd486065e1d3b8d0a9a9e49d"

headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BUBBLE_API_KEY}"
    }

def acquire_lock():
    """
    lock フィールドを無条件に 1 に更新する。
    すでに lock=1 でも上書きされるのでご注意ください。
    """
    try:
        queue_table.update_item(
            Key={"namespace": "default", "user_id": "#META#"},
            UpdateExpression="SET #lk = :locked",
            ExpressionAttributeNames={"#lk": "lock"},
            ExpressionAttributeValues={":locked": 1},
        )
        print("ロックを(強制的に)セットしました (lock=1)")
    except Exception as e:
        print(f"ロック設定エラー: {e}")

def release_lock():
    """
    lock を無条件に 0 に更新する。
    """
    try:
        queue_table.update_item(
            Key={"namespace": "default", "user_id": "#META#"},
            UpdateExpression="SET #lk = :unlock",
            ExpressionAttributeNames={"#lk": "lock"},
            ExpressionAttributeValues={":unlock": 0},
        )
        print("ロックを解放しました (lock=0)")
    except Exception as e:
        print(f"ロック解放エラー: {e}")

def update_queue_meta(players):
    try:
        new_rate_list = []
        new_range_list = []
        print("update_queue_meta p:",players)
        for player in players:
            rating = player["rate"] 
            spread_count = player["range_spread_count"]
            spread_speed = player["range_spread_speed"]
            new_rate_list.append(rating)
            new_range_list.append(50 + spread_speed * spread_count)

        # METAデータに rate_list, range_list を一度に更新
        queue_table.update_item(
            Key={"namespace": "default", "user_id": "#META#"},
            UpdateExpression="SET rate_list = :rl, range_list = :rnl",
            ExpressionAttributeValues={
                ":rl": new_rate_list,
                ":rnl": new_range_list,
            })
    except Exception as e:
        print("error at update_queue_meta", e)
        

def update_bubble_queue_via_ws():
    # 接続している全ユーザーの connection_id を取得
    try:
        connection_resp = connection_table.scan(ProjectionExpression="connection_id")
        connection_ids = [
            item["connection_id"] for item in connection_resp.get("Items", [])
        ]
        asyncio.run(broadcast_queue_count(connection_ids))
    except Exception as e:
        print("error at update_bubble_queue_via_ws", e)

# 20秒毎に呼ばれるマッチメイク処理のエントリポイント
def handle(event, context):
    """
    1. QueueTableからプレイヤーを取得し、
       ユーザーごとの最新レートと許容レンジを計算する。
    2. プレイヤーをレートの高い順にソートし、上からグループ形成の試行を行う。
    3. 10人グループが形成できたらマッチ成立とし、グループに入らなかったプレイヤーは
       次回のためにrange_spread_countをインクリメントする。
    """
    acquire_lock()
    print("start match making process")
    try:
        waiting_users = get_waiting_users(queue_table)
        print(waiting_users)
        if len(waiting_users) < 10:
            print("users in the queue is not enough. End the match making with increment the range.")
            for p in waiting_users:
                
                increment_range_spread_count(p["user_id"])
            update_queue_meta(waiting_users)
            # update_bubble_queue_via_ws()
            return {
                "statusCode": 200,
                "body": "No matches found. Incremented range_spread_count for all waiting players."
            }
        
        # 各プレイヤーの最新レートと許容レンジを計算
        players = []
        for user in waiting_users:
            user_id = user["user_id"]
            # ★ 将来拡張: blocking, role を利用した処理をここに挿入可能
            rating = user["rate"] #get_user_rating(user_id)
            best = user["best"] #get_user_rating(user_id)
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
                "rate": rating,
                "best": best,
                "min_rating": min_rating,
                "max_rating": max_rating,
                "range_spread_speed": spread_speed,
                "range_spread_count": spread_count,
                "inqueued_unixtime": user["inqueued_unixtime"],
                "discord_id": user["discord_id"] # キュー情報に含む
            })
        
        # 降順（高い順）にソート
        #players.sort(key=lambda x: x["rate"], reverse=True)
        
        # インキューした時間順（古い順＝先に入った順）にソート
        players.sort(key=lambda x: x["inqueued_unixtime"])
        
        # グループ形成：できるだけ多くの10人グループを形成する
        #matched_groups = form_matches_from_pool(players)

        # BFSを採用したメソッドを使用
        matched_groups = find_valid_groups(players)
        
        if matched_groups:

            print("match group made")
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
            print("idbase, new, unusedvc",match_id_base, new_match_id_base, unused_vc)
            queue_table.update_item(
                Key={"namespace": "default", "user_id": "#META#"},
                UpdateExpression="SET LatestMatchID = :newID, UnusedVC = :vcList",
                ExpressionAttributeValues={":newID": new_match_id_base, ":vcList": unused_vc}
            )
            
            # 形成できなかったプレイヤーはrate_spread_countをインクリメント
            used_ids = {p["user_id"] for group in matched_groups for p in group}
            remined_user = []
            for p in players:
                if p["user_id"] not in used_ids:
                    increment_range_spread_count(p["user_id"])
                    remined_user.append(p)
            update_queue_meta(remined_user)
            # update_bubble_queue_via_ws()
            return {
                "statusCode": 200,
                "body": f"Matched {len(matched_groups)} groups. Match IDs assigned from {match_id_base+1} to {new_match_id_base}."
            }
        else:
            # 1件もマッチ成立しなかった場合は、全員のrange_spread_countをインクリメント
            for p in players:
                increment_range_spread_count(p["user_id"])

            update_queue_meta(players)
            # update_bubble_queue_via_ws()
            return {
                "statusCode": 200,
                "body": "No matches found. Incremented range_spread_count for all waiting players."
            }
        
        
    except Exception as e:
        print("ERROR: ", e) 
    finally:
        
        release_lock()

def get_waiting_users(queue):
    """マッチキューからマッチング待ちのユーザを取得"""
    response = queue.query(
        IndexName="rate_index",
        KeyConditionExpression=Key("namespace").eq("default"),
        FilterExpression=Attr("user_id").ne("#META#"),  # user_id != "#META#"
        ProjectionExpression="user_id, rate, best, blocking, desired_role, range_spread_speed, range_spread_count, discord_id, inqueued_unixtime"
    )
    return response["Items"]

def get_user_rating(user_id):
    """UserTableから最新のレートを取得する"""
    resp = user_table.get_item(Key={"user_id": user_id})
    if "Item" in resp:
        return resp["Item"].get("rate", 1500)
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

    # ★ グループをレート順（降順：レートが高い順）にソートする
    group.sort(key=lambda x: x["rate"], reverse=True)
    
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
            "namespace":"default",
            "match_id": int(match_id),  # match_idはint型
            "team_A": [[p["user_id"], int(p["rate"]), int(p["best"])] for p in team_a_players],
            "team_B": [[p["user_id"], int(p["rate"]), int(p["best"])] for p in team_b_players],
            "matched_unix_time": int(time.time()),
            "status": "matched",
            "user_reports": [],
            "penalty_player": [],
            "judge_timeout_count": 0,
            "vc_A": int(vc_a),
            "vc_B": int(vc_a + 1)
        }
    )
    asyncio.run(notify_bubble([p["user_id"]for p in team_a_players]+[p["user_id"]for p in team_b_players], match_id))
    
    # ⑤ Discordへ通知送信
    asyncio.run(notify_discord(match_id, vc_a, vc_b, team_a_discord, team_b_discord))




def increment_range_spread_count(user_id):
    """マッチに入らなかったプレイヤーのrange_spread_countをインクリメントする"""
    queue_table.update_item(
        Key={"namespace": "default", "user_id": user_id},
        UpdateExpression="SET #c = #c + :inc",
        ExpressionAttributeNames={"#c": "range_spread_count"},
        ExpressionAttributeValues={":inc": 1}
    )
    print(user_id, "count has been incremented")

# 各プレイヤーの assigned_match_id を新しい match_id に更新する処理
def update_assigned_match_ids(user_ids, match_id):
    for uid in user_ids:
        user_table.update_item(
            Key={"namespace": "default","user_id": uid},
            UpdateExpression="SET assigned_match_id = :m",
            ExpressionAttributeValues={":m": match_id}
        )

async def notify_discord(match_id, vc_a, vc_b, team_a, team_b):

    """
    DiscordのWebhookを用いてマッチ通知を送信する関数。
    """
    # プレイヤーIDリストをスペース区切りで連結
    team_a_str = " ".join([f"<@{p}>" for p in team_a])
    team_b_str = " ".join([f"<@{p}>" for p in team_b])
    
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

    
    
async def notify_bubble(players, match_id):
    # Bubbleへ通知
    json = {
        "players": players,
        "match_id": int(match_id)
    }

    requests.request(method="POST", url=BUBBLE_ASSIGN_MATCH_URL, headers=headers, json=json)
    

def dfs_group(players, start_index, current_group, current_min, current_max):
    """
    深さ優先探索／バックトラッキングで、現在の共通許容レンジ [current_min, current_max]
    を満たしながら、候補プレイヤーを追加して10人グループを構築する。
    
    :param players: 各要素が辞書 {"user_id", "rate", "min_rating", "max_rating", ...} のリスト
    :param start_index: この段階での探索開始インデックス
    :param current_group: これまでに選ばれたプレイヤーのリスト
    :param current_min: 現在の共通許容レンジの下限
    :param current_max: 現在の共通許容レンジの上限
    :return: もし有効な10人グループが見つかればそのリストを返す。見つからなければ None
    """
    if len(current_group) == 10:
        return current_group

    for i in range(start_index, len(players)):
        candidate = players[i]
        # 候補プレイヤーの実際のレートが、現在の共通許容レンジに含まれているかチェック
        if not (current_min <= candidate["rate"] <= current_max):
            continue

        # 候補の許容レンジとの交差を計算
        new_min = max(current_min, candidate["min_rating"])
        new_max = min(current_max, candidate["max_rating"])
        if new_min > new_max:
            continue

        # 候補をグループに追加して再帰的に探索
        new_group = current_group + [candidate]
        result = dfs_group(players, i + 1, new_group, new_min, new_max)
        if result is not None:
            return result

    return None

def find_valid_groups(players):
    """
    プレイヤーリストからDFS／バックトラッキングで条件を満たす10人グループを
    重複なく全て見つける。例えば、30人の候補から3グループが見つかれば、
    [group1, group2, group3] のリストを返す。
    
    :param players: 各要素が辞書 {"user_id", "rate", "min_rating", "max_rating", ...} のリスト
    :return: 有効なグループ（各グループは10人のリスト）のリスト。グループが見つからなければ空リスト
    """
    groups = []
    # candidates をコピー。なお、プレイヤーリストはあらかじめ希望の順（例えば、降順やインキュー順）にソートしておく
    remaining_players = players[:]
    
    while len(remaining_players) >= 10:
        # 初期の共通レンジは (-∞, +∞)
        group = dfs_group(remaining_players, 0, [], -math.inf, math.inf)
        if group is None:
            break  # 残りからは10人グループが作れない
        
        groups.append(group)
        # グループに含まれるプレイヤーの user_id を除外
        used_ids = set(p["user_id"] for p in group)
        remaining_players = [p for p in remaining_players if p["user_id"] not in used_ids]
    
    return groups