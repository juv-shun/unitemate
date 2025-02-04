import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
from pydantic import BaseModel, ValidationError, field_serializer

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["USER_TABLE"])


class UserCreationModel(BaseModel):
    namespace: str = "default"
    user_id: str
    rate: int
    updated_unixtime: datetime = datetime.now(ZoneInfo("Asia/Tokyo")).replace(
        microsecond=0
    )

    @field_serializer("updated_unixtime")
    def serialize_updated_unixtime(self, updated_unixtime: datetime) -> int:
        return int(updated_unixtime.timestamp())


def handle(event, _):
    # バリデーションチェック
    try:
        model = UserCreationModel(**json.loads(event["body"]))
    except ValidationError as e:
        return {"statusCode": 422, "body": e.json()}

    table.put_item(Item=model.model_dump())
    return {"statusCode": 200, "body": None}
