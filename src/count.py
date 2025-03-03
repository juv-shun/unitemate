import sys
import csv

def main():
    csv_file_path = "dynamodb_export.csv"
    count = 0
    
    # CSV を読み込み
    with open(csv_file_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        
        # ヘッダー行があれば1行読み飛ばす (必要に応じてコメントアウトしてください)
        next(reader, None)
        
        for row in reader:
            # 空行をスキップ
            if not row:
                continue
            
            # pokepoke_num_record が 1 以上かどうかを判定
            # CSV の2列目が pokepoke_num_record と仮定
            if int(row[1]) >= 1:
                count += int(row[1])
    
    print(count//2)

import math

def dfs_group(players, start_index, current_group, current_min, current_max):
    """
    深さ優先探索／バックトラッキングで、現在の共通許容レンジ [current_min, current_max]
    を満たしながら、候補プレイヤーを追加して10人グループを構築する。
    
    :param players: 各要素が辞書 {"user_id", "rate", "min_rating", "max_rating", ...} のリスト
    :param start_index: この段階での探索開始インデックス
    :param current_group: これまでに選ばれたプレイヤーのリスト
    :param current_min: 現在の共通許容レンジの下限
    :param current_max: 現在の共通許容レンジの上限
    :return: もし有効な10人グループが見つかればそのリストを返す。見つからなければ None
    """
    if len(current_group) == 10:
        return current_group

    for i in range(start_index, len(players)):
        candidate = players[i]
        # 候補プレイヤーの実際のレートが、現在の共通許容レンジに含まれているかチェック
        if not (current_min <= candidate["rate"] <= current_max):
            continue

        # 候補の許容レンジとの交差を計算
        new_min = max(current_min, candidate["min_rating"])
        new_max = min(current_max, candidate["max_rating"])
        if new_min > new_max:
            continue

        # 候補をグループに追加して再帰的に探索
        new_group = current_group + [candidate]
        result = dfs_group(players, i + 1, new_group, new_min, new_max)
        if result is not None:
            return result

    return None

def find_valid_groups(players):
    """
    プレイヤーリストからDFS／バックトラッキングで条件を満たす10人グループを
    重複なく全て見つける。例えば、30人の候補から3グループが見つかれば、
    [group1, group2, group3] のリストを返す。
    
    :param players: 各要素が辞書 {"user_id", "rate", "min_rating", "max_rating", ...} のリスト
    :return: 有効なグループ（各グループは10人のリスト）のリスト。グループが見つからなければ空リスト
    """
    groups = []
    # candidates をコピー。なお、プレイヤーリストはあらかじめ希望の順（例えば、降順やインキュー順）にソートしておく
    remaining_players = players[:]
    
    while len(remaining_players) >= 10:
        # 初期の共通レンジは (-∞, +∞)
        group = dfs_group(remaining_players, 0, [], -math.inf, math.inf)
        if group is None:
            break  # 残りからは10人グループが作れない
        
        groups.append(group)
        # グループに含まれるプレイヤーの user_id を除外
        used_ids = set(p["user_id"] for p in group)
        remaining_players = [p for p in remaining_players if p["user_id"] not in used_ids]
        print(remaining_players)
        print()
    
    return groups


# --- 使用例 ---
if __name__ == "__main__":
    # サンプルデータ（例）
    players = [
        {"user_id": "A", "rate": 1627, "min_rating": 1557, "max_rating": 1697},
        {"user_id": "B", "rate": 1618, "min_rating": 1568, "max_rating": 1668},
        {"user_id": "C", "rate": 1543, "min_rating": 1473, "max_rating": 1613},
        {"user_id": "D", "rate": 1534, "min_rating": 1444, "max_rating": 1624},
        {"user_id": "E", "rate": 1534, "min_rating": 1404, "max_rating": 1664},
        {"user_id": "F", "rate": 1526, "min_rating": 1416, "max_rating": 1636},
        {"user_id": "G", "rate": 1514, "min_rating": 1424, "max_rating": 1604},
        {"user_id": "H", "rate": 1510, "min_rating": 1420, "max_rating": 1600},
        {"user_id": "I", "rate": 1507, "min_rating": 1457, "max_rating": 1557},
        {"user_id": "J", "rate": 1495, "min_rating": 1365, "max_rating": 1625},
        {"user_id": "K", "rate": 1488, "min_rating": 1238, "max_rating": 1738},
        {"user_id": "AA", "rate": 1627, "min_rating": 1557, "max_rating": 1697},
        {"user_id": "BB", "rate": 1618, "min_rating": 1568, "max_rating": 1668},
        {"user_id": "CC", "rate": 1543, "min_rating": 1473, "max_rating": 1613},
        {"user_id": "DD", "rate": 1534, "min_rating": 1444, "max_rating": 1624},
        {"user_id": "enumerateE", "rate": 1534, "min_rating": 1404, "max_rating": 1664},
        {"user_id": "FFF", "rate": 1526, "min_rating": 1416, "max_rating": 1636},
        {"user_id": "GSS", "rate": 1514, "min_rating": 1424, "max_rating": 1604},
        {"user_id": "HA", "rate": 1510, "min_rating": 1420, "max_rating": 1600},
        {"user_id": "Isad", "rate": 1507, "min_rating": 1457, "max_rating": 1557},
        {"user_id": "JD", "rate": 1495, "min_rating": 1365, "max_rating": 1625},
        {"user_id": "KD", "rate": 1488, "min_rating": 1238, "max_rating": 1738},
         {"user_id": "ACC", "rate": 1627, "min_rating": 1557, "max_rating": 1697},
        {"user_id": "BCC", "rate": 1618, "min_rating": 1568, "max_rating": 1668},
        {"user_id": "CCC", "rate": 1543, "min_rating": 1473, "max_rating": 1613},
        {"user_id": "DCC", "rate": 1534, "min_rating": 1444, "max_rating": 1624},
        {"user_id": "ECC", "rate": 1534, "min_rating": 1404, "max_rating": 1664},
        {"user_id": "FCC", "rate": 1526, "min_rating": 1416, "max_rating": 1636},
        {"user_id": "GCC", "rate": 1514, "min_rating": 1424, "max_rating": 1604},
        {"user_id": "HCC", "rate": 1510, "min_rating": 1420, "max_rating": 1600},
        {"user_id": "ICC", "rate": 1507, "min_rating": 1457, "max_rating": 1557},
        {"user_id": "JCC", "rate": 1495, "min_rating": 1365, "max_rating": 1625},
        {"user_id": "KCC", "rate": 1488, "min_rating": 1238, "max_rating": 1738},
        {"user_id": "AAAAAAA", "rate": 1627, "min_rating": 1557, "max_rating": 1697},
        {"user_id": "BAAAAAAAA", "rate": 1618, "min_rating": 1568, "max_rating": 1668},
        {"user_id": "CAAAAAAAAAA", "rate": 1543, "min_rating": 1473, "max_rating": 1613},
        {"user_id": "DAAAA", "rate": 1534, "min_rating": 1444, "max_rating": 1624},
        {"user_id": "EAAAA", "rate": 1534, "min_rating": 1404, "max_rating": 1664},
        {"user_id": "FAAAA", "rate": 1526, "min_rating": 1416, "max_rating": 1636},
        {"user_id": "GAAAA", "rate": 1514, "min_rating": 1424, "max_rating": 1604},
        {"user_id": "HAAAA", "rate": 1510, "min_rating": 1420, "max_rating": 1600},
        {"user_id": "IAAAA", "rate": 1507, "min_rating": 1457, "max_rating": 1557},
        {"user_id": "JAAAA", "rate": 1495, "min_rating": 1365, "max_rating": 1625},
        {"user_id": "KAAAA", "rate": 1488, "min_rating": 1238, "max_rating": 1738}, 
        {"user_id": "AQQQ", "rate": 1627, "min_rating": 1557, "max_rating": 1697},
        {"user_id": "BQ", "rate": 1618, "min_rating": 1568, "max_rating": 1668},
        {"user_id": "CQ", "rate": 1543, "min_rating": 1473, "max_rating": 1613},
        {"user_id": "DQ", "rate": 1534, "min_rating": 1444, "max_rating": 1624},
        {"user_id": "QE", "rate": 1534, "min_rating": 1404, "max_rating": 1664},
        {"user_id": "FQ", "rate": 1526, "min_rating": 1416, "max_rating": 1636},
        {"user_id": "GQ", "rate": 1514, "min_rating": 1424, "max_rating": 1604},
        {"user_id": "QH", "rate": 1510, "min_rating": 1420, "max_rating": 1600},
        {"user_id": "QI", "rate": 1507, "min_rating": 1457, "max_rating": 1557},
        {"user_id": "JQ", "rate": 1495, "min_rating": 1365, "max_rating": 1625},
        {"user_id": "QmmK", "rate": 1488, "min_rating": 1238, "max_rating": 1738},
        {"user_id": "QA", "rate": 1627, "min_rating": 1557, "max_rating": 1697},
        {"user_id": "QmmKB", "rate": 1618, "min_rating": 1568, "max_rating": 1668},
        {"user_id": "CQmmK", "rate": 1543, "min_rating": 1473, "max_rating": 1613},
        {"user_id": "DQmmK", "rate": 1534, "min_rating": 1444, "max_rating": 1624},
        {"user_id": "EQmmK", "rate": 1534, "min_rating": 1404, "max_rating": 1664},
        {"user_id": "FQmmK", "rate": 1526, "min_rating": 1416, "max_rating": 1636},
        {"user_id": "QmmKG", "rate": 1514, "min_rating": 1424, "max_rating": 1604},
        {"user_id": "QmmKH", "rate": 1510, "min_rating": 1420, "max_rating": 1600},
        {"user_id": "QmmKI", "rate": 1507, "min_rating": 1457, "max_rating": 1557},
        {"user_id": "QmmKJ", "rate": 1495, "min_rating": 1365, "max_rating": 1625},
        {"user_id": "QmmKQmmKK", "rate": 1488, "min_rating": 1238, "max_rating": 1738},
        # さらに追加して30人などにできる
    ]
    
    # たとえば、既にプレイヤーリストがソート済みならそのまま
    groups = find_valid_groups(players)
    if groups:
        print("Found groups:")
        for idx, group in enumerate(groups):
            print(f"Group {idx+1}: {[p['user_id'] for p in group]}")
    else:
        print("No valid groups found.")
