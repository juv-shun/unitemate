import os

import boto3

import requests
from time import sleep
from requests.exceptions import RequestException
import time
from datetime import datetime, timezone
import json


ELO_CONST = 16  # レート計算に使用する固定値


# 受け取ってSQSに送る
def handle(event, context):
    sqs = boto3.client("sqs")
    queue_url = os.environ["AGGREGATION_QUEUE"]

    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(
            {
                "action": "user_match",
                "match_id": event["match_id"],
                "timestamp": int(time.time()),  # タイムスタンプを追加
                "user_id": event["user_id"],
            }
        ),
        MessageGroupId="MatchProcessing",  # FIFOキュー用
    )
    print(f"Enqueued match {event['match_id']} with MessageId: {response['MessageId']}")


# SQSを順番に処理する
def process_queue(event, context):
    """
    SQSイベントを受け取り、試合を順番に処理する。
    """
    for record in event["Records"]:
        message = json.loads(record["body"])
        try:
            action = message["action"]
        except:
            action = "user_match"

        if action == "update_ranking":
            try:
                print("[INFO] Received ranking update request.")
                result_message = update_ranking_order()
                print(result_message)
            except Exception as e:
                print(f"Error processing ranking: {str(e)}")

        elif action == "onhold_recheck":
            match_id = message["match_id"]
            retry_count = message["match_id"]
            
            print(f"Processing match {match_id}")

            if is_enough_report(match_id):
                judge(match_id)
            else:
                schedule_recheck(match_id)

        
        else:
            match_id = message["match_id"]
            print(f"Processing match {match_id}")

            

            try:
                handle({"match_id": match_id}, context)
            except Exception as e:
                print(f"Error processing match {match_id}: {str(e)}")

# 処理の中身
def judge_timeout(event, context):
    # 試合開始から20分後から5分おきに呼び出して、呼ぶたびに必要な報告数を減らしていく

    pass

# 処理の中身
def judge_report_num(event, context):
    # 

    pass

def judge(event, context)

# 処理の中身　暫定順位を算出　一旦PASS
def update_ranking_order():
    pass
