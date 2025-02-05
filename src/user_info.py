import os
import json
import boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal

# 環境変数から DynamoDB テーブル名を取得
USER_TABLE = os.environ["USER_TABLE"]
RECORD_TABLE = os.environ["RECORD_TABLE"]

# DynamoDB リソースとテーブルの初期化
dynamodb = boto3.resource("dynamodb")
user_table = dynamodb.Table(USER_TABLE)
record_table = dynamodb.Table(RECORD_TABLE)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj)  # 必要に応じて float(obj) に変更可能
        return super(DecimalEncoder, self).default(obj)


def handler(event, context):
    """
    GET /users/{user_id} のリクエストを処理し、対応するプレイヤーデータと最新の50件の試合レコードを返す。
    """
    try:
        # pathParameters から user_id を取得
        user_id = event["pathParameters"]["user_id"]
        print(f"Received request for user_id: {user_id}")

        # DynamoDB から user_id に対応するユーザーデータを取得
        user_response = user_table.get_item(Key={"namespace": "default", "user_id": user_id})

        # ユーザーデータが存在しない場合
        if "Item" not in user_response:
            # プレイヤーデータが無い場合、新規作成
            Item = {
                "namespace": "default",
                "user_id": user_id,
                "pokepoke_num_record": 0,
                "pokepoke_num_win": 0,
                "rate": 1500,
                "pokepoke_max_rate": 1500,
                # "pokepoke_records": [],
                "pokepoke_last_rate_delta": 0,
                "pokepoke_winrate": 0,
                "pokepoke_last_match_id": 0,
                "ranking_order": 9999,
            }
            user_table.put_item(Item=Item)

            user_item = Item

        else:
            # ユーザーデータを取得
            user_item = user_response["Item"]

        print(f"User data retrieved: {user_item}")

        # 最新の50件の試合データを取得
        latest_matches = []
        try:
            match_response = record_table.query(
                IndexName="started_date_index",  # GSIを指定
                KeyConditionExpression=Key("user_id").eq(user_id),
                ScanIndexForward=False,  # 降順（最新順）
                Limit=50,
                ProjectionExpression="used_pokemon, match_id, rate_delta, started_date, winlose, team_A, team_B",
            )
            latest_matches = match_response.get("Items", [])

            print(f"Retrieved {len(latest_matches)} latest matches for user_id {user_id}")
        except Exception as e:
            print(f"Error fetching match records: {str(e)}")
            # 試合データ取得失敗時もユーザーデータは返す
            latest_matches = []

        # 必要なデータのみを返す
        user_data_response = {
            "user_id": user_item.get("user_id"),
            "num_record": int(user_item.get("num_record", 0)),
            "num_win": int(user_item.get("num_win", 0)),
            "rate": int(user_item.get("rate", 1500)),
            "max_rate": int(user_item.get("max_rate", 1500)),
            "winrate": int(user_item.get("winrate", 0)),
            "last_rate_delta": int(user_item.get("last_rate_delta", 0)),
            "latest_matches": latest_matches,  # 最新の50件の試合データを追加
        }
        # シリアライズ前にデータの型をログ出力
        print("user_data_response types:")
        for key, value in user_data_response.items():
            if isinstance(value, list):
                print(f"{key}: List of {type(value[0]) if value else 'Empty List'}")
                for idx, item in enumerate(value):
                    print(f"  latest_matches[{idx}]: {item}")
            else:
                print(f"{key}: {type(value)}")

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},  # 必要に応じて調整
            "body": json.dumps(user_data_response, cls=DecimalEncoder),
        }

    except Exception as e:
        print(f"Error fetching user data: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},  # 必要に応じて調整
            "body": json.dumps({"message": "Internal server error."}),
        }