import boto3

# DynamoDB のリソース作成
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')

# 削除対象のテーブル
TABLES_TO_CLEAR = ["prd-unitemate-record-table"]

def delete_all_items(table_name):
    table = dynamodb.Table(table_name)
    print(f"🚀 Deleting items from table: {table_name}")

    # ページネーション対応のスキャン
    last_evaluated_key = None

    while True:
        # `scan()` で全データ取得
        if last_evaluated_key:
            response = table.scan(ExclusiveStartKey=last_evaluated_key)
        else:
            response = table.scan()

        items = response.get("Items", [])
        print(f"Found {len(items)} items in {table_name}.")

        # 一括削除
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"user_id": item["user_id"], "match_id": item["match_id"]})
                #batch.delete_item(Key={"namespace": item["namespace"], "match_id": item["match_id"]})  # 主キーに合わせて修正
                #batch.delete_item(Key={"namespace": item["namespace"], "user_id": item["user_id"]})  # 主キーに合わせて修正

        # 次のページがあるか確認
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    print(f"✅ All items deleted from {table_name}")

if __name__ == "__main__":
    for table in TABLES_TO_CLEAR:
        delete_all_items(table)
