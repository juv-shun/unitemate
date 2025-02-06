import os
import boto3
import requests
from time import sleep
from requests.exceptions import RequestException
import time
from datetime import datetime, timezone
import json



MATCH_TABLE = os.environ["MATCH_TABLE"]
USER_TABLE = os.environ["USER_TABLE"]
RECORD_TABLE = os.environ["RECORD_TABLE"]

dynamodb = boto3.resource("dynamodb")
matches_table = dynamodb.Table(MATCH_TABLE)
user_table = dynamodb.Table(USER_TABLE)
record_table = dynamodb.Table(RECORD_TABLE)
# boto3クライアントの初期化
sqs = boto3.client('sqs')
# FIFOキューのURL。環境変数で管理
QUEUE_URL = os.environ["AGGREGATION_QUEUE"]

ELO_CONST = 16  # レート計算に使用する固定値


def is_report_enough(reports, timeout_count):
    timeout_count_list = [10, 9, 8, 8, 7, 7, 7, 6, 6, 6, 6]
    if timeout_count >= len(timeout_count_list):
        return -1
    else:
        return len(reports) >= timeout_count_list[timeout_count]


# 処理の中身
def judge_timeout(event, context):
    # 試合開始から20分後から5分おきに呼び出して、呼ぶたびに必要な報告数を減らしていく
    match_id = event["match_id"]
    # DynamoDB から match_id に対応する試合データを取得
    match_response = matches_table.get_item(Key={"namespace": "default", "match_id": match_id})
    
    
    # データが存在しない場合
    if "Item" not in match_response:
        print("ERROR: Match is not found")
        return {"statusCode": 200, "body": None}
    
    match_item = match_response["Item"]
    report = match_item.get("user_reports", [])
    timeout_count = match_item.get("judge_timeout_count", 0)

    # レポートの数をカウントし、必要な報告数と比較して条件があっているか確認
    
    # 足りていない場合、再度条件を緩くしてタイムアウトを設定
    if not is_report_enough(report, timeout_count):
        
        response = send_process_result_message(event, context, 300)
        return response
        

    else: # 足りている場合、レポートの数から結果を判定




        # 通報が多いユーザーのペナルティ判定

        # 結果に応じてユーザーのレートを更新

        pass

# 処理の中身
def judge_report_num(event, context):
    # 

    pass

def judge(event, context):
    pass

# 処理の中身　暫定順位を算出　一旦PASS
def update_ranking_order():
    pass