# coding: utf_8
# -----------------------------------------------------------------------------------#
# @file           daily_notify.py
# @brief          仁川国際空港 貨物スケジュール 毎日定時通知システム
# @author         GitHub Copilot
# @date           2025/11/01
# $Version:       1.01
# $Revision:      2025/11/01 - 到着便対応追加
# @note           毎日22時に7日分のデータ（出発便・到着便）を取得してDiscordに通知
#                 キャッシュファイルのクリーンアップ機能を含む
# @attention      Windows Task Schedulerで毎日22:00に実行される想定
#                 出発便・到着便それぞれ別のキャッシュファイルに保存
# @par            History
#                 v1.00 (2025/11/01) - 初期実装・キャッシュ保存機能追加
#                 v1.01 (2025/11/01) - 到着便データ取得・通知機能追加
# Copyright (c) 2025. All Rights reserved.
#
# -----------------------------------------------------------------------------------#

import os
import shutil
import json
import math
from pathlib import Path
from datetime import datetime, timedelta
from incheon_cargo_scraper import IncheonCargoScraper
from dotenv import load_dotenv


# ======================================================================================#
# @function name:   save_cache_data
# @function start
def save_cache_data(df, log_dir='log'):
    """
    ---------------------------------------------------------------------
    関数概要：  取得したデータをキャッシュファイルに保存
    - DataFrameをJSON形式で保存
    - NaN値をNoneに変換してJSON互換性を確保
    ----------------------------------------------------------------------
    Args:
        df (pd.DataFrame): 保存するDataFrame
        log_dir (str): ログディレクトリパス（デフォルト: 'log'）
    ---------------------------------------------------------------------
    Returns:
        なし
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.01 (2025/11/01) - 到着便対応追加
    ---------------------------------------------------------------------
    """
    cache_file = Path(log_dir) / 'last_data_cache.json'
    
    try:
        # DataFrameを辞書のリストに変換し、NaN値をNoneに変換
        data = df.to_dict('records')
        cleaned_data = []
        
        for item in data:
            cleaned_item = {}
            for key, value in item.items():
                if isinstance(value, float) and math.isnan(value):
                    cleaned_item[key] = None
                else:
                    cleaned_item[key] = value
            cleaned_data.append(cleaned_item)
        
        # JSONファイルに保存
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cleaned_data, f, ensure_ascii=False, indent=2)
        
        print(f"  キャッシュファイルを保存: {cache_file}")
    except Exception as e:
        print(f"  警告: キャッシュファイルの保存に失敗 - {e}")
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   clean_log_files
# @function start
def clean_log_files():
    """
    ---------------------------------------------------------------------
    関数概要：  logディレクトリ内のCSVとJSONファイルを削除
    - 古いログファイルをクリーンアップ
    - 削除したファイル数を表示
    ----------------------------------------------------------------------
    Args:
        なし
    ---------------------------------------------------------------------
    Returns:
        なし
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.00 (2025/11/01) - 初期実装
    ---------------------------------------------------------------------
    """
    log_dir = 'log'
    if not os.path.exists(log_dir):
        return
    
    deleted_count = 0
    for filename in os.listdir(log_dir):
        if filename.endswith('.csv') or filename.endswith('.json'):
            file_path = os.path.join(log_dir, filename)
            try:
                os.remove(file_path)
                deleted_count += 1
                print(f"  削除: {filename}")
            except Exception as e:
                print(f"  削除失敗: {filename} - {e}")
    
    if deleted_count > 0:
        print(f"✓ {deleted_count}個のログファイルを削除しました")
    else:
        print("削除するログファイルはありませんでした")
    print()
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   main
# @function start
def main():
    """
    ---------------------------------------------------------------------
    関数概要：  メイン処理
    - ログファイルのクリーンアップ（コメントアウト済み）
    - 7日分のデータ（出発便・到着便）を取得
    - Discordに通知
    - キャッシュファイルを保存
    ----------------------------------------------------------------------
    Args:
        なし
    ---------------------------------------------------------------------
    Returns:
        なし
    ---------------------------------------------------------------------
    Notes:
        - author         GitHub Copilot
        - revision       v1.01 (2025/11/01) - 到着便対応追加
    ---------------------------------------------------------------------
    """
    print("=" * 60)
    print("【毎日22時実行】仁川国際空港 貨物スケジュール")
    print("=" * 60)
    print(f"実行日時: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")
    print()
    
    # ログファイルを削除（CSV出力を停止したためコメントアウト）
    # print("--- ログファイルのクリーンアップ ---")
    # clean_log_files()
    
    # 環境変数の読み込み
    load_dotenv()
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    
    if not webhook_url:
        print("エラー: DISCORD_WEBHOOK_URLが設定されていません")
        print("  .envファイルを確認してください")
        return
    
    # 今日から7日分の日付を生成
    today = datetime.now()
    start_date = today.strftime('%Y%m%d')
    end_date = (today + timedelta(days=6)).strftime('%Y%m%d')
    
    print(f"期間: {start_date} ~ {end_date}")
    print(f"空港: NGO (名古屋)")
    print("=" * 60)
    print()
    
    # スクレイピング実行
    scraper = IncheonCargoScraper()
    
    # 出発便を取得
    print("\n【出発便データ取得】")
    print("=" * 60)
    df_departure = scraper.scrape_multiple_dates(
        start_date=start_date,
        end_date=end_date,
        airport='NGO',
        flight_type='departure'
    )
    
    # 到着便を取得
    print("\n【到着便データ取得】")
    print("=" * 60)
    df_arrival = scraper.scrape_multiple_dates(
        start_date=start_date,
        end_date=end_date,
        airport='NGO',
        flight_type='arrival'
    )
    
    # データの確認
    has_departure = not df_departure.empty
    has_arrival = not df_arrival.empty
    
    if not has_departure and not has_arrival:
        print("⚠ データが取得できませんでした")
        return
    
    if has_departure:
        print(f"出発便: {len(df_departure)} 件のデータを取得しました")
    if has_arrival:
        print(f"到着便: {len(df_arrival)} 件のデータを取得しました")
    print()
    
    # Discordに通知
    print("Discordに通知を送信します...")
    
    if not webhook_url:
        print("エラー: Webhook URLが設定されていません")
        return
    
    # スクレイパーのwebhook_urlを設定
    scraper.discord_webhook_url = webhook_url
    
    success_departure = False
    success_arrival = False
    
    # 出発便の通知
    if has_departure:
        print("\n【出発便の通知送信】")
        success_departure = scraper.send_discord_notification(
            df=df_departure,
            start_date=start_date,
            end_date=end_date,
            airport='NGO',
            flight_type='departure'
        )
    
    # 到着便の通知
    if has_arrival:
        print("\n【到着便の通知送信】")
        success_arrival = scraper.send_discord_notification(
            df=df_arrival,
            start_date=start_date,
            end_date=end_date,
            airport='NGO',
            flight_type='arrival'
        )
    
    # どちらか一方でも成功していればキャッシュを保存
    success = success_departure or success_arrival
    
    if success:
        # 通知成功後、キャッシュファイルを保存（出発便と到着便を分けて保存）
        if has_departure:
            save_cache_data(df_departure, log_dir='log')
        if has_arrival:
            # 到着便用のキャッシュファイルを別名で保存
            import pandas as pd
            cache_file = Path('log') / 'last_data_cache_arrival.json'
            try:
                data = df_arrival.to_dict('records')
                cleaned_data = []
                for item in data:
                    cleaned_item = {}
                    for key, value in item.items():
                        if isinstance(value, float) and math.isnan(value):
                            cleaned_item[key] = None
                        else:
                            cleaned_item[key] = value
                    cleaned_data.append(cleaned_item)
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(cleaned_data, f, ensure_ascii=False, indent=2)
                print(f"  到着便キャッシュファイルを保存: {cache_file}")
            except Exception as e:
                print(f"  警告: 到着便キャッシュファイルの保存に失敗 - {e}")
        
        print()
        print("=" * 60)
        print("✓ 通知の送信が完了しました")
        print("=" * 60)
    else:
        print()
        print("=" * 60)
        print("✗ 通知の送信に失敗しました")
        print("=" * 60)
# @function end
# ======================================================================================#


if __name__ == '__main__':
    main()
