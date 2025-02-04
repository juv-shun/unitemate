import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
from pydantic import BaseModel, ValidationError, field_serializer


LAMBDA_FUNC_MAKEJUDGE = os.environ["LAMBDA_FUNC_NAME"]
REPORT_QUEUE = os.environ["REPORT_QUEUE"]
MATCH_TABLE = os.environ["MATCH_TABLE"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(MATCH_TABLE)
sqs = boto3.client("sqs")
record_table = dynamodb.Table(os.environ["RECORD_TABLE"])

result_dict = {"lose": 0, "win": 1, "invalid": 2, "null": 3}


class MatchReportModel(BaseModel):
    namespace: str = "default"
    match_id: int
    user_id: str
    result: str
    vioration_report: str
    banned_pokemon: str
    picked_pokemon: str
    pokemon_move1: str
    pokemon_move2: str
    report_unixtime: datetime = datetime.now(ZoneInfo("Asia/Tokyo")).replace(
        microsecond=0
    )

    @field_serializer("inqueued_unixtime")
    def serialize_inqueued_unixtime(self, inqueued_unixtime: datetime) -> int:
        return int(inqueued_unixtime.timestamp())


# 受け取ってSQSに送る
def handle(event, context):
    """ユーザからマッチング結果を受け取り SQS キューに送信"""
    try:
        # バリデーションチェック
        model = MatchReportModel(**json.loads(event["body"]))
    except ValidationError as e:

        print("report was not valid")
        return {"statusCode": 422, "body": e.json()}

    try:
        if model.match_id == 1:
            return {
                "statusCode": 422,
                "body": json.dumps({"error": "Invalid match_id: 1"}),
            }

        # SQS キューに送信
        rate_request = {"match_id": model.match_id, "report_data": model.model_dump()}
        response = sqs.send_message(
            QueueUrl=REPORT_QUEUE, MessageBody=json.dumps(rate_request)
        )
        print(f"Message sent to SQS: {response['MessageId']}")

        # ユーザーに受信レスポンスを返す
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Report received successfully"}),
        }
    except:
        print("report queue got error")
        return {"statusCode": 422, "body": e.json()}


# SQSを順番に処理する
def process_report_queue(event, _):
    """SQS キューからレポートを取得して順番に処理"""
    for record in event["Records"]:
        try:
            # メッセージを取得
            message_body = record["body"]
            report_data = json.loads(message_body)

            # 既存の report 関数を呼び出して処理
            fake_event = {"body": json.dumps(report_data["report_data"])}
            report(fake_event, _)
            print("report process successfully done")
        except Exception as e:
            print(f"Error processing record: {e}")


# 処理の中身
def report(event, _):
    """ユーザからマッチング結果を受取り結果を保存するAPI"""
    print("event")
    # バリデーションチェック
    try:
        model = MatchReportModel(**json.loads(event["body"]))
    except ValidationError as e:
        return {"statusCode": 422, "body": e.json()}

    # 試合結果の報告をMatchテーブルに格納
    table.update_item(
        Key=model.keys_dict(),
        AttributeUpdates={
            "user_reports": {
                "Value": [model.content_dict()],
                "Action": "ADD",
            }
        },
    )

    record_table.update_item(
        Key={
            "user_id": model.user_id,
            "match_id": int(model.match_id),
        },
        UpdateExpression="SET #key1 = :val1",
        ExpressionAttributeNames={
            "#key1": "reported_result",
        },
        ExpressionAttributeValues={
            ":val1": int(result_dict[model.result]),
        },
    )

    # 後続バッチを起動
    boto3.client("lambda").invoke(
        FunctionName=LAMBDA_FUNC_MAKEJUDGE,
        InvocationType="Event",
        Payload=json.dumps({"match_id": model.match_id, "user_id": model.user_id}),
    )

    return {"statusCode": 200, "body": None}
