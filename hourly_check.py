# coding: utf_8
# -----------------------------------------------------------------------------------#
# @file           hourly_check.py
# @brief          仁川国際空港 貨物スケジュール 時間ごと変更検知システム
# @author         GitHub Copilot
# @date           2025/11/01
# $Version:       1.01
# $Revision:      2025/11/01 - 到着便対応追加
# @note           1時間ごとに実行し、前回データとの差分を検出してDiscord通知
#                 出発便・到着便それぞれ独立して変更を検出
#                 変更がない場合は通知をスキップすることで無駄な通知を削減
# @attention      Windows Task Schedulerで1時間ごとに実行される想定
#                 last_data_cache.jsonとlast_data_cache_arrival.jsonに前回データを保存
# @par            History
#                 v1.00 (2025/11/01) - 初期実装・NaN値正規化対応
#                 v1.01 (2025/11/01) - 到着便データ取得・変更検出機能追加
# Copyright (c) 2025. All Rights reserved.
#
# -----------------------------------------------------------------------------------#

from incheon_cargo_scraper import IncheonCargoScraper
from datetime import datetime, timedelta
import sys
import os
import json
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd

# .envファイルを読み込む
load_dotenv()

# logディレクトリを作成
LOG_DIR = Path(__file__).parent / 'log'
if not LOG_DIR.exists():
    LOG_DIR.mkdir()

# 前回データを保存するファイル
CACHE_FILE = LOG_DIR / 'last_data_cache.json'
CACHE_FILE_ARRIVAL = LOG_DIR / 'last_data_cache_arrival.json'


# ======================================================================================#
# @function name:   load_previous_data
# @function start
def load_previous_data():
    """
    ---------------------------------------------------------------------
    関数概要：  前回取得したデータを読み込む
    - キャッシュファイル(last_data_cache.json)から前回のデータを取得
    - ファイルが存在しない場合や読み込み失敗時はNoneを返す
    ----------------------------------------------------------------------
    Args:
        なし
    ---------------------------------------------------------------------
    Returns:
        list or None: 前回取得したデータ（辞書のリスト）、失敗時はNone
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.00 (2025/11/01) - 初期実装
    ---------------------------------------------------------------------
    """
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: キャッシュファイルの読み込みに失敗 - {e}")
            return None
    return None
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   save_current_data
# @function start
def save_current_data(data):
    """
    ---------------------------------------------------------------------
    関数概要：  現在のデータをキャッシュファイルに保存
    - NaN値をNoneに変換してJSON互換性を確保
    - 次回の比較用にデータを永続化
    ----------------------------------------------------------------------
    Args:
        data (list): 保存するデータ（辞書のリスト）
    ---------------------------------------------------------------------
    Returns:
        なし
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.00 (2025/11/01) - 初期実装
    ---------------------------------------------------------------------
    """
    try:
        # NaN値をNoneに変換
        cleaned_data = []
        for item in data:
            cleaned_item = {}
            for key, value in item.items():
                if isinstance(value, float):
                    import math
                    if math.isnan(value):
                        cleaned_item[key] = None
                    else:
                        cleaned_item[key] = value
                else:
                    cleaned_item[key] = value
            cleaned_data.append(cleaned_item)
        
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cleaned_data, f, ensure_ascii=False, indent=2)
        print(f"  データをキャッシュに保存: {CACHE_FILE}")
    except Exception as e:
        print(f"警告: キャッシュファイルの保存に失敗 - {e}")
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   normalize_value
# @function start
def normalize_value(value):
    """
    ---------------------------------------------------------------------
    関数概要：  値を正規化する
    - NaN、None、空文字列、文字列"NaN"をすべてNoneに統一
    - データ比較時の誤判定を防ぐ
    ----------------------------------------------------------------------
    Args:
        value: 正規化する値
    ---------------------------------------------------------------------
    Returns:
        正規化された値（NaN系の値はNone、それ以外はそのまま）
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.00 (2025/11/01) - 初期実装
    ---------------------------------------------------------------------
    """
    import math
    # 文字列"NaN"もNoneに変換
    if value is None or value == '' or value == 'NaN':
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   compare_data
# @function start
def compare_data(previous, current):
    """
    ---------------------------------------------------------------------
    関数概要：  データを比較して変更を検出
    - 前回データと現在データを比較
    - 新規追加、削除、時間変更を検出
    ----------------------------------------------------------------------
    Args:
        previous (list): 前回取得したデータ
        current (list): 現在取得したデータ
    ---------------------------------------------------------------------
    Returns:
        tuple: (変更有無(bool), 変更内容の説明(str))
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.00 (2025/11/01) - 初期実装
    ---------------------------------------------------------------------
    """
    if previous is None:
        return True, "初回実行のため全データを通知"
    
    changes = []
    
    # 前回のデータをセットに変換（NaNを正規化）
    prev_flights = set()
    for item in previous:
        # 便名、日付、出発時間をキーにする
        key = (
            normalize_value(item.get('便名')),
            normalize_value(item.get('取得日')),
            normalize_value(item.get('出発時間（予定）')),
            normalize_value(item.get('出発時間（実際）'))
        )
        prev_flights.add(key)
    
    # 現在のデータをセットに変換（NaNを正規化）
    curr_flights = set()
    for item in current:
        key = (
            normalize_value(item.get('便名')),
            normalize_value(item.get('取得日')),
            normalize_value(item.get('出発時間（予定）')),
            normalize_value(item.get('出発時間（実際）'))
        )
        curr_flights.add(key)
    
    # 新規追加されたフライト
    added = curr_flights - prev_flights
    if added:
        changes.append(f"新規: {len(added)}件")
        for flight in added:
            print(f"  + 新規: {flight[0]} ({flight[1]}) - {flight[2]}")
    
    # 削除されたフライト
    removed = prev_flights - curr_flights
    if removed:
        changes.append(f"削除: {len(removed)}件")
        for flight in removed:
            print(f"  - 削除: {flight[0]} ({flight[1]}) - {flight[2]}")
    
    # 出発時間の変更をチェック
    for curr_item in current:
        curr_key = (
            normalize_value(curr_item.get('便名')),
            normalize_value(curr_item.get('取得日')),
            normalize_value(curr_item.get('出発時間（予定）'))
        )
        
        for prev_item in previous:
            prev_key = (
                normalize_value(prev_item.get('便名')),
                normalize_value(prev_item.get('取得日')),
                normalize_value(prev_item.get('出発時間（予定）'))
            )
            
            if curr_key == prev_key:
                # 同じフライトの出発時間（実際）を比較
                prev_actual = normalize_value(prev_item.get('出発時間（実際）'))
                curr_actual = normalize_value(curr_item.get('出発時間（実際）'))
                
                if prev_actual != curr_actual:
                    changes.append(f"時間変更: {curr_key[0]}")
                    prev_str = prev_actual if prev_actual is not None else "未定"
                    curr_str = curr_actual if curr_actual is not None else "未定"
                    print(f"  ⚠ 時間変更: {curr_key[0]} ({curr_key[1]}) {prev_str} → {curr_str}")

    
    if changes:
        return True, ", ".join(changes)
    else:
        return False, "変更なし"
# @function end
# ======================================================================================#


# ======================================================================================#


# ======================================================================================#
# @function name:   main
# @function start
def main():
    """
    ---------------------------------------------------------------------
    関数概要：  メイン処理 - 1時間ごとのチェック
    - 7日分のデータ（出発便・到着便）を取得
    - 前回データと比較
    - 変更があった場合のみDiscordに通知
    ----------------------------------------------------------------------
    Args:
        なし
    ---------------------------------------------------------------------
    Returns:
        なし (終了コードをsys.exitで返す)
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.01 (2025/11/01) - 到着便対応追加
    ---------------------------------------------------------------------
    """
    
    # .envファイルから環境変数を取得
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    
    if not webhook_url:
        print("エラー: 環境変数 DISCORD_WEBHOOK_URL が設定されていません")
        print("\n.envファイルを作成して以下の内容を記載してください:")
        print("  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...")
        sys.exit(1)
    
    # 日付を計算
    today = datetime.now()
    start_date = today.strftime('%Y%m%d')
    end_date = (today + timedelta(days=6)).strftime('%Y%m%d')
    
    print("=" * 60)
    print("【1時間ごとチェック】仁川国際空港 貨物スケジュール")
    print("=" * 60)
    print(f"実行日時: {today.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"期間: {start_date} ~ {end_date}")
    print(f"空港: NGO (名古屋)")
    print("=" * 60)
    
    # スクレイパーを初期化
    scraper = IncheonCargoScraper()
    
    # 出発便データを取得
    print("\n【出発便データ取得】")
    print("=" * 60)
    df_departure = scraper.scrape_multiple_dates(
        start_date=start_date,
        end_date=end_date,
        airport='NGO',
        output_format=None,
        flight_type='departure'
    )
    
    # 到着便データを取得
    print("\n【到着便データ取得】")
    print("=" * 60)
    df_arrival = scraper.scrape_multiple_dates(
        start_date=start_date,
        end_date=end_date,
        airport='NGO',
        output_format=None,
        flight_type='arrival'
    )
    
    # データの確認
    has_departure_data = df_departure is not None and len(df_departure) > 0
    has_arrival_data = df_arrival is not None and len(df_arrival) > 0
    
    if not has_departure_data and not has_arrival_data:
        print("\n! データが取得できませんでした")
        sys.exit(1)
    
    # 変更検出フラグ
    has_changes_overall = False
    
    # 出発便の変更チェック
    if has_departure_data:
        current_data_departure = df_departure.to_dict('records')
        print("\n【出発便】前回データとの比較中...")
        previous_data_departure = load_previous_data()
        has_changes_dep, change_summary_dep = compare_data(previous_data_departure, current_data_departure)
        print(f"出発便比較結果: {change_summary_dep}")
        has_changes_overall = has_changes_overall or has_changes_dep
    
    # 到着便の変更チェック
    if has_arrival_data:
        current_data_arrival = df_arrival.to_dict('records')
        print("\n【到着便】前回データとの比較中...")
        # 到着便用のキャッシュファイルから読み込み
        if CACHE_FILE_ARRIVAL.exists():
            try:
                with open(CACHE_FILE_ARRIVAL, 'r', encoding='utf-8') as f:
                    previous_data_arrival = json.load(f)
            except Exception as e:
                print(f"警告: 到着便キャッシュファイルの読み込みに失敗 - {e}")
                previous_data_arrival = None
        else:
            previous_data_arrival = None
        
        has_changes_arr, change_summary_arr = compare_data(previous_data_arrival, current_data_arrival)
        print(f"到着便比較結果: {change_summary_arr}")
        has_changes_overall = has_changes_overall or has_changes_arr
    
    if has_changes_overall:
        print("\n変更が検出されました。Discordに通知を送信します...")
        
        success_departure = False
        success_arrival = False
        
        # 出発便の通知
        if has_departure_data and has_changes_dep:
            print("\n【出発便の通知送信】")
            success_departure = scraper.send_discord_notification(
                df_departure, start_date, end_date, 'NGO', flight_type='departure'
            )
        
        # 到着便の通知
        if has_arrival_data and has_changes_arr:
            print("\n【到着便の通知送信】")
            success_arrival = scraper.send_discord_notification(
                df_arrival, start_date, end_date, 'NGO', flight_type='arrival'
            )
        
        success = success_departure or success_arrival
        
        if success:
            # 成功したら現在のデータを保存
            if has_departure_data:
                save_current_data(current_data_departure)
            if has_arrival_data:
                # 到着便データを別ファイルに保存
                try:
                    cleaned_data = []
                    for item in current_data_arrival:
                        cleaned_item = {}
                        for key, value in item.items():
                            if isinstance(value, float):
                                import math
                                if math.isnan(value):
                                    cleaned_item[key] = None
                                else:
                                    cleaned_item[key] = value
                            else:
                                cleaned_item[key] = value
                        cleaned_data.append(cleaned_item)
                    
                    with open(CACHE_FILE_ARRIVAL, 'w', encoding='utf-8') as f:
                        json.dump(cleaned_data, f, ensure_ascii=False, indent=2)
                    print(f"  到着便データをキャッシュに保存: {CACHE_FILE_ARRIVAL}")
                except Exception as e:
                    print(f"警告: 到着便キャッシュファイルの保存に失敗 - {e}")
            
            print("\n" + "=" * 60)
            print("✓ 変更を検出し、通知を送信しました")
            print("=" * 60)
            sys.exit(0)
        else:
            print("\n! Discord通知に失敗しました")
            sys.exit(1)
    else:
        print("\n変更がないため、通知をスキップします")
        # 変更がなくても現在のデータを保存（次回比較用）
        if has_departure_data:
            save_current_data(current_data_departure)
        if has_arrival_data:
            try:
                cleaned_data = []
                for item in current_data_arrival:
                    cleaned_item = {}
                    for key, value in item.items():
                        if isinstance(value, float):
                            import math
                            if math.isnan(value):
                                cleaned_item[key] = None
                            else:
                                cleaned_item[key] = value
                        else:
                            cleaned_item[key] = value
                    cleaned_data.append(cleaned_item)
                
                with open(CACHE_FILE_ARRIVAL, 'w', encoding='utf-8') as f:
                    json.dump(cleaned_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"警告: 到着便キャッシュファイルの保存に失敗 - {e}")
        
        print("\n" + "=" * 60)
        print("✓ チェック完了（変更なし）")
        print("=" * 60)
        sys.exit(0)
# @function end
# ======================================================================================#


if __name__ == '__main__':
    main()
