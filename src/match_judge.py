import os
import boto3
import requests
from time import sleep
from requests.exceptions import RequestException
import time
from datetime import datetime, timezone
import json
import uuid



MATCH_TABLE = os.environ["MATCH_TABLE"]
USER_TABLE = os.environ["USER_TABLE"]
RECORD_TABLE = os.environ["RECORD_TABLE"]

dynamodb = boto3.resource("dynamodb")
matches_table = dynamodb.Table(MATCH_TABLE)
user_table = dynamodb.Table(USER_TABLE)
record_table = dynamodb.Table(RECORD_TABLE)
queue_table = dynamodb.Table(os.environ["MATCH_QUEUE"])
# boto3クライアントの初期化
sqs = boto3.client('sqs')
# FIFOキューのURL。環境変数で管理
QUEUE_URL = os.environ["AGGREGATION_QUEUE"]
BUBBLE_PENALTY = os.environ["BUBBLE_PENALTY"]
BUBBLE_API_KEY = "da60b1aedd486065e1d3b8d0a9a9e49d"
headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BUBBLE_API_KEY}"
    }
ELO_CONST = 16  # レート計算に使用する固定値


def is_report_enough(reports, timeout_count):

    timeout_count_list = [10, 9, 8, 8, 7, 7, 7, 6, 6, 6, 6, 5,5,5,5,5,]
    if timeout_count >= len(timeout_count_list):
        return -1
    else:
        return len(reports) >= timeout_count_list[int(timeout_count)]

def get_result(reports):
    """
    reports: ["A-win", "B-win", "Invalid", ...] 7～10個程度
    戻り値: "A-win", "B-win", あるいは "Invalid"
    """
    a_count = reports.count("A-win")
    b_count = reports.count("B-win")
    i_count = reports.count("Invalid")

    # 1) "A-win" が "B-win"+"Invalid" を上回るか？
    if a_count > b_count + i_count:
        return "A-win"

    # 2) "B-win" が "A-win"+"Invalid" を上回るか？
    if b_count > a_count + i_count:
        return "B-win"

    # 3) いずれの条件も満たさない
    return "Invalid"

def gather_match(event, context):
    print("gather_match called")
    # 現在のUTCタイムスタンプを取得
    current_time = int(time.time())
    two_hours_ago = current_time - 2 * 3600  # 2時間前

    # status = "matched" のデータを取得
    response = matches_table.query(
        IndexName="status_index",
        KeyConditionExpression="#namespace = :namespace AND #status = :status",
        FilterExpression="#matched_unixtime >= :two_hours_ago",
        ExpressionAttributeNames={
            "#namespace": "namespace",
            "#status": "status",
            "#matched_unixtime": "matched_unix_time",
        },
        ExpressionAttributeValues={
            ":namespace": "default",
            ":status": "matched",
            ":two_hours_ago": two_hours_ago,  # 過去2時間以内を絞り込み
        },
        ProjectionExpression="match_id"

    )
    for match in response["Items"]:
        send_process_result_message({"match_id": int(match["match_id"])}, context)

    return {
                "statusCode": 200,
                "body": f" Match IDs called for judge."
            }


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
    print(f"judge start for match {match_id}... timeout count is: {timeout_count}")
    # レポートの数をカウントし、必要な報告数と比較して条件があっているか確認
    
    if is_report_enough(report, timeout_count) == -1:

        pass
    # 足りていない場合、再度条件を緩くしてタイムアウトを設定
    elif not is_report_enough(report, timeout_count):
        print("not enough report")
        matches_table.update_item(
            Key={"namespace": "default", "match_id": match_id},
            UpdateExpression="SET judge_timeout_count = :new_count",
            ExpressionAttributeValues={":new_count": timeout_count + 1},
        )
        return
        

    else: # 足りている場合、レポートの数から結果を判定
        try:
            print("report enough ")
            result = get_result([r.get("result") for r in report]) # Awin, Bwin, or Invalid
            matches_table.update_item(
                Key={"namespace": "default", "match_id": match_id},
                UpdateExpression="SET #sts = :done",
                ExpressionAttributeNames={"#sts": "status"},  
                ExpressionAttributeValues={":done": "done"},
            )
            chardict = {}
            viodict = {}
            #報告から各ユーザーの使用ポケモンと、通報プレイヤーを特定
            for r in report:
                chardict[r.get("user_id")] = r.get("picked_pokemon")
                for viorate_user in r.get("vioration_report").split(", "):
                    if viorate_user in viodict.keys():
                        viodict[viorate_user] += 1
                    else:
                        viodict[viorate_user] = 0

                
            if result!= "Invalid":  # AwinかBwinであれば続行
                teamA = match_item.get("team_A")
                teamB = match_item.get("team_B")

                for i in range(5):
                    UserA_rate = teamA[i][1]
                    UserB_rate = teamB[i][1]
                    rate_result = calculate_rate(UserA_rate, UserB_rate, result)  # [new_rate_a, new_rate_b]
                    
                    rate_delta_a = rate_result[0] - UserA_rate
                    rate_delta_b = rate_result[1] - UserB_rate

                    # 結果に応じてユーザーのレートを更新
                    # started_date = response["Item"].get("matched_unixtime")
                    # deck_types = get_decktype(UserA, UserB, reports)
                    pokeA = chardict[teamA[i][0]] if teamA[i][0] in chardict.keys() else "null"
                    pokeB = chardict[teamB[i][0]] if teamB[i][0] in chardict.keys() else "null"
                    started_date = match_item.get("matched_unix_time")
                    update_player_data(teamA[i][0], rate_delta_a, result == "A-win", match_id, started_date, pokeA)
                    update_player_data(teamB[i][0], rate_delta_b, result == "B-win", match_id, started_date, pokeB)

            # 通報が多いユーザーのペナルティ判定
            for k,v in viodict.items():
                if v > 4:
                    print("penalty for user", k)
                    penalty(k)

            vc_a = match_item.get("vc_A")  # or "vc_a" など実際のキー名に合わせる
            if vc_a is not None:
                # queue_tableの#META# アイテムに対して、UnusedVCリストに vc_a を追加
                queue_table.update_item(
                    Key={"namespace": "default", "user_id": "#META#"},
                    UpdateExpression="SET #unused_vc = list_append(if_not_exists(#unused_vc, :emptyList), :vcValue)",
                    ExpressionAttributeNames={"#unused_vc": "UnusedVC"},
                    ExpressionAttributeValues={
                        ":emptyList": [],
                        ":vcValue": [vc_a]
                    }
                )
                print(f"Returned VC {vc_a} to UnusedVC list.")


            

        except Exception as e:
            print("error :", e)



# 処理の中身
def judge_report_num(event, context):
    # 

    pass

def judge(event, context):
    pass

# 処理の中身　暫定順位を算出　一旦PASS
def update_ranking_order():
    pass

def send_process_result_message(event, context):
    message_body = json.dumps({
        "action": "match_judge",
        "payload": event
    })
    response = sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=message_body,
        MessageGroupId="ProcessQueue",
        MessageDeduplicationId=str(uuid.uuid4()),
    )
    print(f"Enqueued process_result with MessageId: {response['MessageId']}")
    return response


def elo16(rate_win, rate_lose):
    resultab = round(ELO_CONST * (1 - (1 / (10 ** ((rate_lose - rate_win) / 400) + 1))))
    return [rate_win + resultab, rate_lose - resultab]


def calculate_rate(user_a, user_b, match_res):
    return_list = []

    if match_res == "A-win":
        return_list = elo16(user_a, user_b)
    elif match_res == "B-win":
        return_list = elo16(user_b, user_a)
        return_list = [return_list[1], return_list[0]]  # Aのレートが先頭になるよう入れ替え

    return return_list  # [new_rate_a, new_rate_b]

def update_player_data(user_id, rate_delta, win, match_id, started_date, pokemon):
    # プレイヤーのデータを取得
    response = user_table.get_item(
        Key={
            "namespace": "default",
            "user_id": user_id,
        },
    )
    try:
        lastmatchID = response["Item"].get("unitemate_last_match_id")  # ひとつ前の試合ID
    except KeyError:
        # プレイヤーデータが無い場合、新規作成
        Item = {
                "namespace": "default",
                "user_id": user_id,
                "unitemate_num_record": 0,
                "unitemate_num_win": 0,
                "rate": 1500,
                "unitemate_max_rate": 1500,
                "unitemate_last_rate_delta": 0,
                "unitemate_winrate": 0,
                "unitemate_last_match_id": 0,
            }
        user_table.put_item(Item=Item)
        lastmatchID = -1

        response = user_table.get_item(
            Key={
                "namespace": "default",
                "user_id": user_id,
            },
        )

    if lastmatchID != match_id:  # 二重記録を防ぐため最後のIDをチェック
        num_record = response["Item"].get("unitemate_num_record",0)  # 試合数
        num_win = response["Item"].get("unitemate_num_win",0)  # 勝利数
        rate = response["Item"].get("rate",1500)  # レート
        maxrate = response["Item"].get("unitemate_max_rate",1500)  # 最高レート
        # connection_ids = response["Item"].get("connection_ids", [])
        # recordlist = response.get("pokepoke_records", [])

        # 更新するデータを計算
        new_num_rec = num_record + 1
        new_num_win = num_win + 1 if win else num_win
        new_winrate = round((new_num_win) * 100 / (new_num_rec))
        corrected_rate_delta = rate_delta+5 if num_record<20 else rate_delta

        new_rate = rate + corrected_rate_delta
        new_max_rate = max(maxrate, new_rate)

        record_table.put_item(
            Item={
                "user_id": user_id,
                "match_id": int(match_id),
                "pokemon": pokemon,
                "rate_delta": int(corrected_rate_delta),
                "started_date": int(started_date),
                "winlose": int(1 if win else 0),  # 0 lose, 1 win, 2 invalid
            }
        )
    

        # プレイヤーデータを更新
        user_table.update_item(
            Key={
                "namespace": "default",
                "user_id": user_id,
            },
            UpdateExpression="SET #key1 = :val1, #key2 = :val2, #key3 = :val3, #key4 = :val4, #key5 = :val5, #key6 = :val6, #key7 = :val7",
            ExpressionAttributeNames={
                "#key1": "unitemate_num_record",
                "#key2": "unitemate_num_win",
                "#key3": "rate",
                "#key4": "unitemate_last_rate_delta",
                "#key5": "unitemate_winrate",
                "#key6": "unitemate_last_match_id",
                "#key7": "unitemate_max_rate",
            },
            ExpressionAttributeValues={
                ":val1": new_num_rec,
                ":val2": new_num_win,
                ":val3": new_rate,
                ":val4": corrected_rate_delta,
                ":val5": new_winrate,
                ":val6": match_id,
                ":val7": new_max_rate,
            },
        )

        # bubbleに更新データを送信（WebSocket経由に変更）
        '''
        try:
            message_data = {
                "action": "updateStatus",
                "UserID": user_id,
                "rate": int(new_rate),
                "maxrate": int(new_max_rate),
                "winnum": int(new_num_win),
                "winrate": int(new_winrate),
                "recordcnt": int(new_num_rec),
                "last_delta": int(rate_delta),
                "order": int(rankorder),
            }
            print(f"try post to connections: {connection_ids}")
            asyncio.run(post_to_user(connection_ids, message_data))
        except Exception as e:
            print(f"Error sending WebSocket update to user {user_id}: {e}")'''
        

def penalty(user_id):
    # プレイヤーのデータを取得
    response = user_table.get_item(
        Key={
            "namespace": "default",
            "user_id": user_id,
        },
    )
    if "Item" not in response:
        return
    correction = response["Item"].get("unitemate_num_record", 0) // 50
    json = {
        "player": user_id,
        "penaltycorrction": int(correction)
    }

    requests.request(method="POST", url=BUBBLE_PENALTY, headers=headers, json=json)