import os
import json
import boto3
import logging
from boto3.dynamodb.conditions import Key
from decimal import Decimal

# Loggingの設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数から設定を取得
USER_TABLE = os.environ.get("USER_TABLE")

# DynamoDBリソースの初期化
dynamodb = boto3.resource("dynamodb")
user_table = dynamodb.Table(USER_TABLE)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj)  # 必要に応じて float(obj) に変更可能
        return super(DecimalEncoder, self).default(obj)
    



def get_ranking(event, context):
    try:
        print("get ranking")
        # DynamoDBからランキングデータを取得
        response = user_table.query(
            IndexName="rate_index",  # 既存のrate_indexを使用
            KeyConditionExpression=Key("namespace").eq("default"),  
            ScanIndexForward=False,  # 降順にソート
            Limit=110,  # 一度に取得する項目数を設定
        )
        print(response)
        items = response.get("Items", [])
        print(items)
        # 必要なデータ（ユーザーID、勝率、レート）のみを取得
        filtered_items = [
            {
                "user_id": x.get("user_id"),
                "rate": int(x.get("rate", 0)),  # デフォルト値 0
                "unitemate_winrate": int(x.get("unitemate_winrate", 0)),  # デフォルト値 0
            }
            for x in items
        ]
        # レートと勝率に基づいてソート（レート降順、勝率降順）
        sorted_items = sorted(
            filtered_items, key=lambda x: (-int(x.get("rate", 0)), -int(x.get("unitemate_winrate", 0)))
        )

        # 上位50人を選出
        top_rankings = sorted_items[:50] if len(sorted_items) > 50 else sorted_items

        print(top_rankings)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"rankings": top_rankings}, cls=DecimalEncoder),
        }
    except Exception as e:
        logger.error(f"Error in get_ranking: {e}")
        return {"statusCode": 500, "body": json.dumps({"message": "Internal Server Error"})}
    return {"statusCode": 200, "body": None}
