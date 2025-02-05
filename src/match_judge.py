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


ELO_CONST = 16  # レート計算に使用する固定値



# 処理の中身
def judge_timeout(event, context):
    # 試合開始から20分後から5分おきに呼び出して、呼ぶたびに必要な報告数を減らしていく


    # レポートの数をカウントし、必要な報告数と比較して条件があっているか確認
    
    # 足りていない場合、再度条件を緩くしてタイムアウトを設定
    if not is_report_enough(report, timeout_count):
        pass
        

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