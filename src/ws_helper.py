import os
import json
import aioboto3
import time

# 直近のブロードキャスト時刻を保持（コンテナが維持される限り）
last_broadcast_time = 0


async def get_websocket_endpoint():
    region = os.environ["AWS_REGION"]
    stage = os.environ["AWS_STAGE"]
    api_id = os.environ["WEBSOCKET_API_ID"]
    return f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"


async def check_connection(connection_id, endpoint_url):
    async with aioboto3.Session().client(
        "apigatewaymanagementapi", endpoint_url=endpoint_url
    ) as client:
        try:
            await client.get_connection(ConnectionId=connection_id)
            return True
        except client.exceptions.GoneException:
            print(f"Connection {connection_id} is no longer valid.")
            return False


async def post_message_to_connection(connection_id, message_obj, endpoint_url):
    async with aioboto3.Session().client(
        "apigatewaymanagementapi", endpoint_url=endpoint_url
    ) as client:
        try:
            await client.post_to_connection(
                ConnectionId=connection_id, Data=json.dumps(message_obj).encode("utf-8")
            )
        except client.exceptions.GoneException:
            print(f"Connection {connection_id} is gone.")
        except Exception as e:
            print(f"Other error : {e}")


async def post_to_user(connection_ids, message_obj):
    for cid in connection_ids:
        endpoint_url = await get_websocket_endpoint()
        if await check_connection(cid, endpoint_url):
            await post_message_to_connection(cid, message_obj, endpoint_url)


async def broadcast_queue_count(queue_count, connection_ids):
    """
    1秒間に1回だけ最新のキュー情報をすべての接続ユーザーにブロードキャストする
    """
    global last_broadcast_time
    current_time = time.time()

    if current_time - last_broadcast_time < 1:
        return  # 1秒以内のブロードキャストを抑制

    last_broadcast_time = current_time

    if not connection_ids:
        return

    # ブロードキャストメッセージ
    message_data = {"action": "updateQueue", "queueCount": queue_count}

    # WebSocket経由で送信
    await post_to_user(connection_ids, message_data)


async def broadcast_last_queue_info(queue_count, connection_ids):
    if not connection_ids:
        return

    # ブロードキャストメッセージ
    message_data = {"action": "queueInfo", "queueCount": queue_count}

    # WebSocket経由で送信
    await post_to_user(connection_ids, message_data)
