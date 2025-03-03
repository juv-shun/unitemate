

import boto3
import json
import requests
from boto3.dynamodb.conditions import Key

# DynamoDBのリソース作成（リージョンは適宜設定）
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
user_table = dynamodb.Table('prd-unitemate-users')  # ユーザー情報が管理されているテーブル名

# Bubble APIのエンドポイントとAPIキー（環境変数や設定ファイルで管理するのが望ましい）
BUBBLE_API_URL = "https://unitemate.com/api/1.1/wf/award_users_s6"
BUBBLE_API_KEY = "da60b1aedd486065e1d3b8d0a9a9e49d"

# 200件ずつ分割する関数
def chunk_list(lst, chunk_size=50):
    """リストを chunk_size 件ずつに分割する"""
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

def get_all_users():
    """
    DynamoDBのページネーションを考慮し、全ユーザーデータを取得する。
    """
    users = []
    last_evaluated_key = None  # ページネーションのためのキー

    while True:
        # Scan APIの呼び出し
        if last_evaluated_key:
            response = user_table.scan(ExclusiveStartKey=last_evaluated_key)
        else:
            response = user_table.scan()

        users.extend(response.get('Items', []))  # 取得データを追加

        # ページネーションが必要か確認
        last_evaluated_key = response.get('LastEvaluatedKey')
        if not last_evaluated_key:  # もうデータがない場合は終了
            break

    return users

def get_users_sorted_by_rate():
    """
    DynamoDBから全ユーザーのデータを取得し、レート順にソート。
    1位, 2位, 3位, 4位-16位 (TOP16), 17位-50位 (TOP50) の user_id を取得する。
    また、試合数 (pokepoke_num_record) に応じて1000試合以上、500試合以上、100試合以上のプレイヤーもリスト化。
    """
    users = get_all_users()  # ページネーションを考慮して全件取得

    print(f"取得したユーザー数: {len(users)}")

    # レート順にソート（降順）
    users_sorted = sorted(users, key=lambda x: x.get("rate", 0), reverse=True)

    # レートランキングリスト
    top_1 = users_sorted[0]["user_id"] if len(users_sorted) > 0 else None
    top_2 = users_sorted[1]["user_id"] if len(users_sorted) > 1 else None
    top_3 = users_sorted[2]["user_id"] if len(users_sorted) > 2 else None
    top_10 = [user["user_id"] for user in users_sorted[3:10]]  # 4位-16位
    top_100 = [user["user_id"] for user in users_sorted[10:100]]  # 17位-50位

    # 試合数に応じたリスト（pokepoke_num_record を使用）
    match_300 = []
    match_200 = []
    match_100 = []
    match_50 = []

    for user in users:
        match_count = int(user.get("unitemate_num_record", 0))  # 試合数のカウントを pokepoke_num_record に変更
        if match_count >= 300:
            match_300.append(user["user_id"])
        elif match_count >= 200:
            match_200.append(user["user_id"])
        elif match_count >= 100:
            match_100.append(user["user_id"])
        if match_count >= 50:
            match_50.append(user["user_id"])

    # 結果を辞書にまとめて返す
    return {
        "top_1": top_1,
        "top_2": top_2,
        "top_3": top_3,
        "top_10": top_10,
        "top_100": top_100,
        "match_300": match_300,
        "match_200": match_200,
        "match_100": match_100,
        "match_50": match_50
    }


def get_users_sorted_by_rate_50():
    """
    DynamoDBから全ユーザーのデータを取得し、レート順にソート。
    1位, 2位, 3位, 4位-16位 (TOP16), 17位-50位 (TOP50) の user_id を取得する。
    また、試合数 (pokepoke_num_record) に応じて1000試合以上、500試合以上、100試合以上のプレイヤーもリスト化。
    """
    users = get_all_users()  # ページネーションを考慮して全件取得

    print(f"取得したユーザー数: {len(users)}")

    # レート順にソート（降順）
    users_sorted = sorted(users, key=lambda x: x.get("rate", 0), reverse=True)

    return [user["user_id"] for user in users_sorted[:50]]


def give_awards():
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BUBBLE_API_KEY}"
    }

    #users =  user_table.scan().get('Items', [])
    userlist = get_users_sorted_by_rate()
    userlist50 = get_users_sorted_by_rate_50()
    print(len(userlist["match_100"]))
    
    json={
            "first": "",# userlist["top_1"],
            "second": "",# userlist["top_2"],
            "third": "",#userlist["top_3"],
            "top10": [],# userlist["top_10"],
            "top100": [],# userlist["top_100"],
            "100games":  [],#userlist["match_100"],
            "200games":  [],#userlist["match_200"],
            "300games": [],#userlist["match_300"],
            "gold": userlist["match_50"][200:],
        }
    '''
    json = {
        "leadersboard": userlist50
    }'''

    print(json)
    return requests.request(method="POST", url=BUBBLE_API_URL, headers=headers, json=json)
    


if __name__ == "__main__":
    print(give_awards().text)
