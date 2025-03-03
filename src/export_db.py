import csv
import boto3

# boto3 の DynamoDB リソースの作成（適切なリージョン設定など）
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
table = dynamodb.Table('prd-unitemate-users')  # エクスポート対象のテーブル名を指定

def scan_table():
    """
    テーブル全体をスキャンし、ページネーションに対応してすべてのアイテムを取得する。
    """
    items = []
    response = table.scan()
    items.extend(response.get('Items', []))
    
    # LastEvaluatedKey が存在する間、次のページを取得
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        items.extend(response.get('Items', []))
    return items

def write_csv(items, output_filename):
    if not items:
        print("エクスポートするアイテムがありません。")
        return

    # 全アイテムのキーを収集
    headers = set()
    for item in items:
        headers.update(item.keys())
    headers = list(headers)  # 必要に応じて並び替え可能

    with open(output_filename, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        for item in items:
            writer.writerow(item)
    print(f"CSVファイル '{output_filename}' にエクスポート完了。")

if __name__ == "__main__":
    # テーブル全体のアイテムをスキャン（ページネーション対応）
    all_items = scan_table()
    # CSVファイルに書き出し
    write_csv(all_items, "dynamodb_export_users.csv")
