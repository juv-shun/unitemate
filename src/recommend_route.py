import json
import os
from pathlib import Path
from typing import Dict, List

from google import genai
from google.genai import types
from pydantic import BaseModel, RootModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_fixed


class User(BaseModel):
    user_id: str
    desired_role: List[str]
    rate: int


UserList = RootModel[list[User]]


class Recommendation(BaseModel):
    top: str
    top_exp_share: str
    jungle: str
    bottom: str
    bottom_exp_share: str


client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
file_path = Path(__file__).with_name("files") / "system_instruction.txt"
system_instruction = file_path.read_text(encoding="utf-8")
config = types.GenerateContentConfig(
    system_instruction=system_instruction,
    response_mime_type="application/json",
    response_schema=Recommendation,
)


def handle(event, _):
    # バリデーションチェック
    try:
        users = UserList.model_validate(json.loads(event["body"]))
    except ValidationError as e:
        print("ERROR: " + json.dumps(e.json()))
        return {"statusCode": 422, "body": e.json()}

    body = request_gemini(users)
    return {"headers": {"Content-Type": "application/json"}, "statusCode": 200, "body": json.dumps(body)}


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def request_gemini(users: UserList) -> List[Dict]:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=users.model_dump_json(),
        config=config,
    )
    return json.loads(response.text)
