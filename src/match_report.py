import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
import boto3
from pydantic import BaseModel, Field, ValidationError, field_serializer



dynamodb = boto3.resource("dynamodb")
match_table = dynamodb.Table(os.environ["MATCH_TABLE"])
user_table = dynamodb.Table(os.environ["USER_TABLE"])

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
    report_unixtime: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo("Asia/Tokyo")).replace(microsecond=0))


    @field_serializer("report_unixtime")
    def serialize_report_unixtime(self, report_unixtime: datetime) -> int:
        return int(report_unixtime.timestamp())
    
    def keys_dict(self):
        return {"namespace": self.namespace, "match_id": self.match_id}

    def content_dict(self):
        return {
            "user_id": self.user_id,
            "result": self.result,
            "vioration_report": self.vioration_report,
            "banned_pokemon": self.banned_pokemon,
            "picked_pokemon": self.picked_pokemon,
            "pokemon_move1": self.pokemon_move1,
            "pokemon_move2": self.pokemon_move2,
            "report_unixtime": self.serialize_report_unixtime(self.report_unixtime),
        }

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj)  # 必要に応じて float(obj) に変更可能
        return super(DecimalEncoder, self).default(obj)


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
    match_table.update_item(
        Key=model.keys_dict(),
        AttributeUpdates={
            "user_reports": {
                "Value": [model.content_dict()],
                "Action": "ADD",
            }
        },
    )

    # TODO レポートの数が足りているならジャッジ?

    user_table.update_item(
        Key={"namespace": "default", "user_id": model.user_id},
        UpdateExpression="SET assigned_match_id = :zero",
        ExpressionAttributeValues={":zero": 0}
    )
    

    return {"statusCode": 200, "body": None}


def get_info(event, _):
    default_return = {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},  
                    "body": json.dumps({"match_id": 0, "team_A": [],
                                "team_B": [],
                                "team_A_rate": [],
                                "team_B_rate": [],
                                "team_A_best": [],
                                "team_B_best": [],
                                "vc_A": 0,
                                "vc_B": 0,
                                "matched_unix_time": 0,}, cls=DecimalEncoder),
                }
    try:
        # pathParameters から user_id を取得
        user_id = event["pathParameters"]["user_id"]
        print(f"Received request for user_id: {user_id}")
        # DynamoDB から user_id に対応するユーザーデータを取得
        user_response = user_table.get_item(Key={"namespace": "default", "user_id": user_id})
        
        
        # ユーザーデータが存在しない場合
        if "Item" not in user_response:
            return default_return
        else:
            # ユーザーデータを取得
            user_item = user_response["Item"]
            match_id = user_item.get("assigned_match_id", 0)
            # assigned_matchが0の場合
            if match_id == 0:
                return default_return
            else:
                match_data = match_table.get_item(Key={"namespace": "default", "match_id": match_id})
                # matchデータが存在しない
                if "Item" not in match_data:
                    return default_return
                else:
                    match_item = match_data["Item"]
                    teamA = match_item.get("team_A")
                    teamB = match_item.get("team_B")
                    match_data_response = {
                                "match_id": match_id,
                                "team_A": [p[0] for p in teamA],
                                "team_B": [p[0] for p in teamB],
                                "team_A_rate": [p[1] for p in teamA],
                                "team_B_rate": [p[1] for p in teamB],
                                "team_A_best": [p[2] for p in teamA],
                                "team_B_best": [p[2] for p in teamB],
                                "vc_A": match_item.get("vc_A"),
                                "vc_B": match_item.get("vc_B"),
                                "matched_unix_time": int(match_item.get("matched_unix_time", 0)),
                                }
                    return {
                        "statusCode": 200,
                        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},  
                        "body": json.dumps(match_data_response, cls=DecimalEncoder),
                    }



    except Exception as e:
        print("error ", e)
        return default_return
