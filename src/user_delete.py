import json
import os

import boto3
from pydantic import BaseModel, ValidationError

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["USER_TABLE"])


class UserDeletionModel(BaseModel):
    namespace: str = "default"
    user_id: str


def handle(event, _):
    try:
        model = UserDeletionModel(**json.loads(event["body"]))
    except ValidationError as e:
        return {"statusCode": 422, "body": e.json()}

    table.delete_item(Key=model.model_dump())
    return {"statusCode": 200, "body": None}
