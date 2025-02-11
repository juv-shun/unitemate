import json
import logging

import os
import json
import uuid
import boto3

# 各処理を行うモジュールのインポート
from .match_queue import inqueue, dequeue
from .match_make import handle as match_make_handler
from .match_report import report as match_report_handler
from .match_judge import judge_timeout as match_judge_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)



# boto3クライアントの初期化
sqs = boto3.client('sqs')
# FIFOキューのURL。環境変数で管理
QUEUE_URL = os.environ["AGGREGATION_QUEUE"]



def db_process_queue_handler(event, context):
    """
    SQSのメッセージを受け取り、メッセージ内の"action"に応じた処理を呼び出す統合プロセス用のハンドラー。
    
    メッセージ例:
    {
        "action": "match_make",    # enqueue, dequeue, queue_info, match_make,
                                   # notify_users, match_report, process_report,
                                   # match_judge, process_aggregation, user_upsert,
                                   # user_delete, user_info, get_ranking など
        "payload": { ... }         # 各処理に必要なパラメータ
    }
    """
    records = event.get("Records", [])
    for record in records:
        try:
            message_body = record["body"]
            message = json.loads(message_body)
        except Exception as e:
            logger.error(f"メッセージのパースエラー: {e}")
            continue

        action = message.get("action")
        payload = message.get("payload", {})
        logger.info(f"受信アクション: {action} / payload: {payload}")

        try:
            if action == "inqueue":
                inqueue(payload, context)
            elif action == "dequeue":
                dequeue(payload, context)
            elif action == "match_make":
                match_make_handler(payload, context)
            elif action == "match_report":
                match_report_handler(payload, context)
            elif action == "match_judge":
                print('make judge')
                match_judge_handler(payload, context)
            else:
                logger.error(f"不明なアクション: {action}")
        except Exception as ex:
            logger.error(f"アクション {action} の処理中にエラー発生: {ex}")

    return {"statusCode": 200, "body": "すべてのメッセージを正常に処理しました。"}



def send_sqs_message(action: str, payload: dict, group_id: str = "ProcessQueue"):
    """
    SQS FIFOキューにメッセージを送信する共通関数。
    
    :param action: "inqueue", "dequeue", "match_make", "match_report", "process_result", "update_ranking" 等の操作名
    :param payload: 各処理に必要なパラメータを格納した辞書
    :param group_id: FIFOキューのMessageGroupId（全メッセージを1グループにまとめる場合は固定値）
    :return: SQSの送信レスポンス
    """
    message_body = json.dumps({
        "action": action,
        "payload": payload
    })
    response = sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=message_body,
        MessageGroupId=group_id,
        MessageDeduplicationId=str(uuid.uuid4()),
    )
    print(f"Enqueued {action} with MessageId: {response['MessageId']}")
   
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Message enqueued successfully",
            "messageId": response["MessageId"],
        })
    }

def send_inqueue_message(event, _):
    """
    インキュー要求のメッセージを送信する。
    """
    print("inqueue called")
    return send_sqs_message("inqueue", event)

def send_dequeue_message(event, _):
    """
    デキュー要求のメッセージを送信する。
    """
    return send_sqs_message("dequeue", event)

def send_matchmake_message(event, _):
    """
    マッチメイク要求のメッセージを送信する。
    """
    print("match make is called")
    return send_sqs_message("match_make", event)

def send_match_report_message(event, _):
    """
    試合結果報告要求のメッセージを送信する。
    """
    return send_sqs_message("match_report", event)

