import json, decimal
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
user_table = dynamodb.Table(os.environ["USER_TABLE"])
table = dynamodb.Table(os.environ["MATCH_TABLE"])
connection_table = dynamodb.Table(os.environ["CONNECTION_TABLE"])

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            # 整数なら int に、そうでなければ float に変換する例
            return int(o) if o % 1 == 0 else float(o)
        return super(DecimalEncoder, self).default(o)
    
def is_locked():
    """
    #META# アイテムを取得して、lock が 1 なら True を返す。
    なければロックなしとみなす (False)。
    """
    try:
        resp = queue.get_item(
            Key={"namespace": "default", "user_id": "#META#"}
        )
        item = resp.get("Item")
        if not item:
            # #META# アイテムが存在しない場合はロックなしとみなす
            return False
        return item.get("lock", 0) == 1
    except Exception as e:
        print(f"is_locked() エラー: {e}")
        return False

class InqueueModel(BaseModel):
    namespace: str = "default"
    user_id: str
    blocking: str
    desired_role: str
    range_spread_speed: int
    range_spread_count: int
    discord_id: str
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

def update_queue_meta():
    try:
        response = queue.query(
        IndexName="rate_index",
        KeyConditionExpression=Key("namespace").eq("default"),
        ScanIndexForward=False,
        ProjectionExpression=" rate, range_spread_speed, range_spread_count",)
        
        players = response["Items"]
        new_rate_list = []
        new_range_list = []
        for player in players:
            rating = player["rate"] 
            spread_count = player["range_spread_count"]
            spread_speed = player["range_spread_speed"]
            new_rate_list.append(rating)
            new_range_list.append(50 + spread_speed * spread_count)

        # METAデータ rate_list, range_list を更新
        queue.update_item(
            Key={"namespace": "default", "user_id": "#META#"},
            UpdateExpression="SET rate_list = :rl, range_list = :rnl",
            ExpressionAttributeValues={
                ":rl": new_rate_list,
                ":rnl": new_range_list,
            })
    except Exception as e:
        print("error at update_queue_meta", e)

def update_queue_count():
    # 接続している全ユーザーの connection_id を取得　現状未使用
    try:
        connection_resp = connection_table.scan(ProjectionExpression="connection_id")
        connection_ids = [
            item["connection_id"] for item in connection_resp.get("Items", [])
        ]
        print("broadcast_q_count")
        asyncio.run(broadcast_queue_count(connection_ids))
    except Exception as e:
        print("error at update_queue_count: ", e)

def get_user_rating(user_id):
    """
    UserTableから指定された user_id の最新のレートを取得する関数。
    アイテムが存在しない場合、または rating が設定されていない場合は、デフォルト値1500を返す。
    """
    try:
        resp = user_table.get_item(Key={"namespace":"default", "user_id": user_id})
        item = resp.get("Item")
        if item and "rate" in item:
            notinmatch = True
            if "assigned_match_id" in item:
                notinmatch = item["assigned_match_id"] == 0
            return [item["rate"], item["unitemate_max_rate"], notinmatch]
        else:
            return [1500,1500,True]
    except Exception as e:
        print(f"Error retrieving rating for user {user_id}: {e}")
        return [1500,1500,True]

def inqueue(event, _):
    # ロック中の場合は待機またはエラー応答
    if is_locked():
        return {"statusCode": 423, "body": "Match making in progress, please retry later."}
    
    try:
        # イベントのbodyからInqueueModelのインスタンスを生成
        model = InqueueModel(**json.loads(event["body"]))
    except ValidationError as e:
        print("Validation error:", e)
        return {"statusCode": 422, "body": e.json()}
    
    # モデルの辞書を取得
    model_data = model.model_dump()
    
    # user_idを使ってUserTableから最新のrateを取得
    ratinginfo = get_user_rating(model_data["user_id"])
    if ratinginfo[2]:
        # 取得したrateをモデルデータに追加
        model_data["rate"] = ratinginfo[0]
        model_data["best"] = ratinginfo[1]
        # モデルデータをキューに登録
        queue.put_item(Item=model_data)
        update_queue_meta()
        
        return {"statusCode": 200, "body": None}
    else:
        print("user already assigned to another match")
        return  {"statusCode": 200, "body": None}

def dequeue(event, _):
    if is_locked():
        # ロック中の場合は待機 or エラー応答
        return {"statusCode": 423, "body": "Match making in progress, please retry later."}
    try:
        model = DequeueModel(**json.loads(event["body"]))
    except ValidationError as e:
        return {"statusCode": 422, "body": e.json()}

    queue.delete_item(Key=model.model_dump())
    update_queue_meta()
    return {"statusCode": 200, "body": None}


def get_info(event, _):
    """マッチキューの情報を取得するAPI"""
    try:
        # 前回マッチ時刻と前回キュー人数を取得
        response = queue.get_item(Key={"namespace": "default", "user_id": "#META#"})
        if "Item" in response:
            rate_list = response["Item"]["rate_list"]
            range_list = response["Item"]["range_list"]
            ongoing = response["Item"].get("ongoing_matches", 0)
            #ongoing = sum(response["Item"]["match_counter"])
        else:
            rate_list = []
            range_list = []
            ongoing = 0
            #ongoing = 0

        response_body = {
            "rate_list": rate_list,
            "range_list": range_list,
            "ongoing": ongoing,
        }
    except:
        response_body = {
            "rate_list": [],
            "range_list": [],
            "ongoing": 0,
        }

    return {"statusCode": 200, "body": json.dumps(response_body, cls=DecimalEncoder)}
