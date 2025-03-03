import csv

def count_unique_user_ids(csv_file_path):
    unique_user_ids = set()
    with open(csv_file_path, mode='r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = row['user_id']
            unique_user_ids.add(user_id)
    return len(unique_user_ids)

if __name__ == "__main__":
    csv_path = "dynamodb_export_records.csv"  # 実際のCSVファイルパスに置き換えてください
    unique_count = count_unique_user_ids(csv_path)
    print(f"ユニークなUserIDの数: {unique_count}")
