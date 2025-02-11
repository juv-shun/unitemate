import os
import json
import asyncio
import aioboto3  # 正しくインポート
from .match_queue import get_info

async def get_domain_and_stage_async(event):
    """
    WebSocketのManagement APIエンドポイントURLを構築する非同期関数。
    """
    api_id = event["requestContext"]["apiId"]
    stage = event["requestContext"]["stage"]
    region = os.environ["AWS_REGION"]
    endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
    print(f"[Debug] API Gateway Management API Endpoint URL: {endpoint_url}")
    return endpoint_url


async def on_connect_async(event, context):
    """
    $connect ルート。
    WebSocket接続が張られたタイミングで呼ばれる。
    """
    connection_id = event["requestContext"]["connectionId"]
    query_params = event.get("queryStringParameters", {}) or {}
    bubble_user_id = query_params.get("user_id", "")  # Bubble.ioの unique id

    print(f"[OnConnect] connection_id={connection_id}, bubbleUserId={bubble_user_id}")

    if not bubble_user_id:
        return {"statusCode": 400, "body": "Missing user_id"}

    try:
        # DynamoDB リソースの取得
        async with aioboto3.Session().resource("dynamodb") as dynamodb:
            user_table = await dynamodb.Table(os.environ["USER_TABLE"])
            connection_table = await dynamodb.Table(os.environ["CONNECTION_TABLE"])

            # ConnectionTableに保存
            await connection_table.put_item(
                Item={
                    "connection_id": connection_id,
                    "user_id": bubble_user_id,
                    "connected_at": event["requestContext"].get("connectedAt", None),
                }
            )

            # UserTableにconnection_idを追加
            await user_table.update_item(
                Key={"namespace": "default", "user_id": bubble_user_id},
                UpdateExpression="ADD connection_ids :c",
                ExpressionAttributeValues={":c": {connection_id}},
            )

    except Exception as e:
        print("Error in on_connect:", e)

    return {"statusCode": 200}


async def on_disconnect_async(event, context):
    """
    $disconnect ルート。
    WebSocket接続が切れたタイミングで呼ばれる。
    """
    connection_id = event["requestContext"]["connectionId"]
    print(f"[OnDisconnect] {connection_id}")

    try:
        # DynamoDB リソースの取得
        async with aioboto3.Session().resource("dynamodb") as dynamodb:
            connection_table = await dynamodb.Table(os.environ["CONNECTION_TABLE"])
            user_table = await dynamodb.Table(os.environ["USER_TABLE"])

            resp = await connection_table.get_item(Key={"connection_id": connection_id})
            item = resp.get("Item")

            if not item:
                print(f"No record found for connection_id={connection_id}")
                return {"statusCode": 200}

            user_id = item.get("user_id")
            print(f"Found user_id={user_id} for connection_id={connection_id}")

            # UserTableからconnection_idを削除
            await user_table.update_item(
                Key={"namespace": "default", "user_id": user_id},
                UpdateExpression="DELETE connection_ids :c",
                ExpressionAttributeValues={":c": {connection_id}},
            )

            # ConnectionTableからconnection_idを削除
            await connection_table.delete_item(Key={"connection_id": connection_id})
        print(f"Disconnected and cleaned up connection_id={connection_id}")

    except Exception as e:
        print("Error in on_disconnect:", e)

    return {"statusCode": 200}


async def on_message_async(event, context):
    """
    $default ルート。
    クライアントからのメッセージ（JSON）を受信したときに呼ばれる。
    """
    connection_id = event["requestContext"]["connectionId"]
    body_str = event.get("body", "")
    print(f"[OnMessage] connectionId={connection_id}, body={body_str}")

    try:
        data = json.loads(body_str)
    except json.JSONDecodeError:
        data = {}

    action = data.get("action", "")
    print(f"Action: {action}")

    if action == "ping":
        print(f"[Ping] Received ping from {connection_id}")
        await send_websocket_message_async(event, connection_id, {"action": "pong"})
        return {"statusCode": 200, "body": "Pong sent"}

    if action == "echo":
        await send_websocket_message_async(event, connection_id, {"msg": "Echo from server", "received": data})

    if action == "askQueueInfo":
        print(f"[askQueueInfo] Received askQueueInfo from {connection_id}")
        await send_websocket_message_async(event, connection_id, {"action": "updateQueueInfo", "body":get_info(event,context).get("body", ""),})
        return {"statusCode": 200, "body": "Pong sent"}

    return {"statusCode": 200}


async def send_websocket_message_async(event, connection_id, message_obj):
    """
    WebSocketに非同期でメッセージを送信する。
    """
    endpoint_url = await get_domain_and_stage_async(event)
    try:
        async with aioboto3.Session().client("apigatewaymanagementapi", endpoint_url=endpoint_url) as apigw:
            await apigw.post_to_connection(ConnectionId=connection_id, Data=json.dumps(message_obj).encode("utf-8"))
    except apigw.exceptions.GoneException:
        print(f"Connection {connection_id} is gone.")


def on_connect(event, context):
    return asyncio.run(on_connect_async(event, context))


def on_disconnect(event, context):
    return asyncio.run(on_disconnect_async(event, context))


def on_message(event, context):
    return asyncio.run(on_message_async(event, context))


async def connection_test_async():
    """
    テスト用関数: UserTable から dummy_account の connection_ids を取得し、
    各 WebSocket 接続にメッセージを送信する。
    """
    region = os.environ["AWS_REGION"]
    dummy_account = os.environ["DUMMY"]
    user_table_name = os.environ["USER_TABLE"]
    stage = os.environ["AWS_STAGE"]

    # Management API のエンドポイント URL を構築
    api_id = os.environ["WEBSOCKET_API_ID"]
    endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"

    async with aioboto3.Session().resource("dynamodb") as dynamodb:
        user_table = await dynamodb.Table(user_table_name)

        try:
            # UserTable から dummy_account のデータを取得
            response = await user_table.get_item(Key={"namespace": "default", "user_id": dummy_account})
            item = response.get("Item")

            print(item)
            if not item:
                print(f"No record found for user_id={dummy_account}")
                return

            # connection_ids を取得
            connection_ids = item.get("connection_ids", [])
            if not connection_ids:
                print(f"No connection_ids found for user_id={dummy_account}")
                return

            print(f"Found connection_ids: {connection_ids}")

            # 各 connection_id にテストメッセージを送信
            async with aioboto3.Session().client("apigatewaymanagementapi", endpoint_url=endpoint_url) as apigw:
                for connection_id in connection_ids:
                    try:
                        await apigw.post_to_connection(
                            ConnectionId=connection_id,
                            Data=json.dumps({"message": "Test message from connection_test"}).encode("utf-8"),
                        )
                        print(f"Message sent to connection_id={connection_id}")
                    except apigw.exceptions.GoneException:
                        print(f"Connection {connection_id} is gone.")
                    except Exception as e:
                        print(f"Error sending message to {connection_id}: {e}")

        except Exception as e:
            print(f"Error in connection_test: {e}")


def connection_test(event, context):
    """
    非同期関数を同期的に呼び出すためのラッパー。
    """
    return asyncio.run(connection_test_async())
