import os
import random
from datetime import datetime, timedelta, timezone

from time import sleep
import json

from requests.exceptions import RequestException
import boto3
import requests
from boto3.dynamodb.conditions import Attr, Key

from .ws_helper import broadcast_last_queue_info
import asyncio

JST = timezone(timedelta(hours=+9), "JST")

dynamodb = boto3.resource("dynamodb")
queue = dynamodb.Table(os.environ["MATCH_QUEUE"])
table = dynamodb.Table(os.environ["MATCH_TABLE"])
user_data = dynamodb.Table(os.environ["USER_TABLE"])
connection_table = dynamodb.Table(os.environ["CONNECTION_TABLE"])



def update_bubble_queue_via_ws(queue_count):
    try:
        connection_resp = connection_table.scan(ProjectionExpression="connection_id")
        connection_ids = [item["connection_id"] for item in connection_resp.get("Items", [])]
        asyncio.run(broadcast_last_queue_info(queue_count, connection_ids))
    except Exception as e:
        pass


def handle(event, _):
    # マッチキューからマッチング待ちのユーザを取得
    users = get_queue_users(queue)

    # bubbleにキューの数を通知
    matched_unixtime = int(datetime.now(JST).replace(microsecond=0).timestamp())
    lastqueuecnt = len(users)
    print(f"users:{users}")
    # キュー人数が6人以下ならマッチしない
    if lastqueuecnt < 6:
        # 前回マッチ時刻、前回キュー人数を保存
        ongoing = create_previous_match_info(matched_unixtime, users, 0)

        update_bubble_queue_via_ws(lastqueuecnt)

        return []
    print(f"users:{users}")
    
    # ユーザーテーブルを参照して各ユーザーのレートを取得
    users = update_queue_users(users)

    # レートが近い人同士の組み合わせを作成
    matches = make_pairs(users)

    print(f"matche:{matches}")
    # match_id base を決定 -------------
    response = table.query(
        ProjectionExpression="match_id",
        KeyConditionExpression=Key("namespace").eq("default"),
        Limit=1,
        ScanIndexForward=False,
    )

    print(response)
    try:
        match_id_base = response["Items"][0].get("match_id") + 1
    except:
        match_id_base = 1

    match_id_counter = 0

    # match_id base を決定 -------------

    matched_users = []

    match_ids = []
    for match in matches:
        match_id, lobby_id = create_match_record(match, matched_unixtime, match_id_base + match_id_counter)
        match_id_counter += 1
        matched_users.append(match[0])
        matched_users.append(match[1])
        match_ids.append(match_id)
        # Bubble側にマッチ情報を同期処理で通知
        invoke_notification_lambda(
            match_id,
            lobby_id,
            match[0].get("user_id"),
            match[1].get("user_id"),
            match[0].get("deck_type"),
            match[1].get("deck_type"),
            match[0].get("rate"),
            match[1].get("rate"),
            match[0].get("maxrate"),
            match[1].get("maxrate"),
        )

    # マッチキューからマッチしたユーザーを削除
    remove_user_from_queue(matches)

    # 前回マッチ時刻、前回キュー人数を保存
    ongoing = create_previous_match_info(matched_unixtime, users, len(matches))

    inqueue_players = [user.get("user_id") for user in matched_users]

    newqueuecnt = lastqueuecnt - len(inqueue_players)

    update_bubble_queue_via_ws(newqueuecnt)
    notify_via_discord(inqueue_players)

    return match_ids


def invoke_notification_lambda(match_id, lobby_id, playerA, playerB, deckA, deckB, rateA, rateB, maxA, maxB):
    client = boto3.client("lambda")

    response = client.invoke(
        FunctionName=LAMBDA_FUNC_NOTIFY,
        InvocationType="Event",
        Payload=json.dumps(
            {
                "match_id": int(match_id),
                "lobby_id": lobby_id,
                "playerA": playerA,
                "playerB": playerB,
                "deckA": deckA,
                "deckB": deckB,
                "rateA": int(rateA),
                "maxA": int(maxA),
                "rateB": int(rateB),
                "maxB": int(maxB),
            }
        ),
    )


def notify_via_discord(inqueue_players):
    pass


def get_queue_users(queue):
    """マッチキューからマッチング待ちのユーザを取得"""
    response = queue.query(
        IndexName="rate_index",
        KeyConditionExpression=Key("namespace").eq("default"),
        ScanIndexForward=False,
        ProjectionExpression="user_id, rate, deck_type, blocking",
    )
    return response["Items"]


def update_queue_users(users):
    """マッチキューからマッチング待ちのユーザを取得し、必要な場合にユーザーテーブルからレートを取得"""

    for user in users:
        response = user_data.get_item(
            Key={
                "namespace": "default",
                "user_id": user["user_id"],
            }
        )
        try:
            rate = response["Item"].get("rate")
        except:
            rate = 1500
        try:
            maxrate = response["Item"].get("pokepoke_max_rate")
        except:
            maxrate = 1500

        user["rate"] = rate
        user["maxrate"] = maxrate

    print(users)
    return users


def make_pairs(users):
    """
    プレイヤーのリストからペアを作成
    レート順にソートされているリストに対して、２つずつ取得してペアを作る。
    キューの待ち人数が奇数の場合、最後の1人がマッチから漏れ、返却値には含まれない。
    (=キューの待ち人数が奇数の場合、レートが最も低い人が漏れる。前回漏れたとか考慮しない。)
    """

    # レート順でソート
    descending = random.choice([True, False])
    users = sorted(users, key=lambda x: x["rate"], reverse=descending)
    pairs = list()
    used_ids = set()

    i = 0
    while i < len(users):
        if users[i]["user_id"] in used_ids:
            i += 1
            continue

        user1 = users[i]
        # i+1以降を順に確認して条件を満たすユーザーを探す
        for j in range(i + 1, len(users)):
            user2 = users[j]
            if (
                user2["user_id"] not in used_ids
                and user2["user_id"] not in user1["blocking"]
                and user1["user_id"] not in user2["blocking"]
            ):
                # ペア確定
                pairs.append((user1, user2))
                used_ids.add(user1["user_id"])
                used_ids.add(user2["user_id"])
                break
        i += 1

    return pairs


def create_match_record(match, matched_unixtime, match_id):
    print(table)
    print(match_id)
    # TODO lobby ID
    lobby_id = get_random_lobby_id()
    try:
        table.put_item(
            Item={
                "namespace": "default",
                "match_id": match_id,
                # match_idが既存のIDと衝突する可能性もあるが、考慮していないので注意
                "user_id_1": match[0]["user_id"],
                "user_id_2": match[1]["user_id"],
                "status": "matched",
                "matched_unixtime": matched_unixtime,
                # added by rikarazome
                "unified_result": "",
                "user_rate_1": match[0]["rate"],
                "user_rate_2": match[1]["rate"],
                "deck_1": match[0]["deck_type"],
                "deck_2": match[1]["deck_type"],
                "lobby_id": lobby_id,
            },
            ConditionExpression=Attr("match_id").not_exists(),
        )
    except Exception as e:
        # 条件不一致　マッチIDが既存
        print(e)

    return (match_id, lobby_id)


def create_previous_match_info(matched_unixtime, users, cnt_match_made_thistime):
    # match_counter is a list that holds the number of matches made during each of the last 6 match-making attempts.
    lastNtimes = 6  # 過去六回分

    response = queue.get_item(
        Key={
            "namespace": "default",
            "user_id": "#meta#",
        }
    )
    try:
        match_counter = response["Item"].get("match_counter")
        match_counter.append(cnt_match_made_thistime)
    except:
        match_counter = [cnt_match_made_thistime]

    if len(match_counter) > lastNtimes:
        match_counter.pop(0)

    queue.put_item(
        Item={
            "namespace": "default",
            "user_id": "#meta#",  # キューのメタ情報であるため、user_idには特殊文字列を入れておく。
            "previous_user_count": len(users),
            "previous_matched_unixtime": matched_unixtime,
            "match_counter": match_counter,
        },
    )

    return sum(match_counter)


def remove_user_from_queue(matches):
    """
    マッチングしたユーザをキューから消す
    マッチしなかったユーザは削除しない。
    """
    for match in matches:
        for user in match:
            queue.delete_item(Key={"namespace": "default", "user_id": user["user_id"]})
