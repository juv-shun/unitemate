import json
import os

import boto3
from boto3.dynamodb.conditions import Key

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError, field_serializer
import asyncio

from .ws_helper import broadcast_queue_count

dynamodb = boto3.resource("dynamodb")
queue = dynamodb.Table(os.environ["MATCH_QUEUE"])

table = dynamodb.Table(os.environ["MATCH_TABLE"])
connection_table = dynamodb.Table(os.environ["CONNECTION_TABLE"])


class InqueueModel(BaseModel):
    namespace: str = "default"
    user_id: str
    blocking: str
    role: str
    range_spread_speed: int
    range_spread_count: int
    inqueued_unixtime: datetime = datetime.now(ZoneInfo("Asia/Tokyo")).replace(
        microsecond=0
    )

    @field_serializer("inqueued_unixtime")
    def serialize_inqueued_unixtime(self, inqueued_unixtime: datetime) -> int:
        return int(inqueued_unixtime.timestamp())


class DequeueModel(BaseModel):
    namespace: str = "default"
    user_id: str


def get_queue_count():
    # マッチキューの待ち人数を取得
    response1 = queue.query(
        Select="COUNT",
        KeyConditionExpression=Key("namespace").eq("default"),
    )
    return response1["Count"] - 1


def update_queue_count():
    # 接続している全ユーザーの connection_id を取得
    try:
        connection_resp = connection_table.scan(ProjectionExpression="connection_id")
        connection_ids = [
            item["connection_id"] for item in connection_resp.get("Items", [])
        ]
        asyncio.run(broadcast_queue_count(get_queue_count(), connection_ids))
    except Exception as e:
        pass


def inqueue(event, _):
    # バリデーションチェック
    try:
        model = InqueueModel(**json.loads(event["body"]))
    except ValidationError as e:
        return {"statusCode": 422, "body": e.json()}

    queue.put_item(Item=model.model_dump())
    update_queue_count()
    return {"statusCode": 200, "body": None}


def dequeue(event, _):
    try:
        model = DequeueModel(**json.loads(event["body"]))
    except ValidationError as e:
        return {"statusCode": 422, "body": e.json()}

    queue.delete_item(Key=model.model_dump())
    update_queue_count()
    return {"statusCode": 200, "body": None}


def get_info(event, _):
    """マッチキューの情報を取得するAPI"""

    # 前回マッチ時刻と前回キュー人数を取得
    response = queue.get_item(Key={"namespace": "default", "user_id": "#meta#"})
    if "Item" in response:
        matched_unixtime = response["Item"]["previous_matched_unixtime"]
        lastqueuecnt = response["Item"]["previous_user_count"]
        ongoing = sum(response["Item"]["match_counter"])
    else:
        matched_unixtime = 0
        lastqueuecnt = 0
        ongoing = 0

    response_body = {
        "lastqueue": int(lastqueuecnt),
        "lastmatchtime": int(matched_unixtime),
        "ongoing_match_cnt": int(ongoing),
    }

    return {"statusCode": 200, "body": json.dumps(response_body)}
