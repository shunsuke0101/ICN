# coding: utf-8
# -----------------------------------------------------------------------------------#
# @file           ICN/hourly_check.py
# @brief          仁川国際空港 貨物スケジュール 時間ごと変更検知システム
# @author         Kidera Shunsuke
# @date           2025/11/01
# $Version:       2.00
# $Revision:      2026/11/12
# @note           1時間ごとに実行し、前回データとの差分を検出してDiscord通知
#                 出発便・到着便それぞれ独立して変更を検出
#                 変更がない場合は通知をスキップすることで無駄な通知を削減
#
#                 【通知フォーマット】
#                 - 変更があった便だけを、1 便 = 1 メッセージで個別に通知する
#                 - 各メッセージ: 本文に便名・経路・日付と変更内容の要約、
#                   埋め込みに一覧通知と同じ 1 便分の枠（+ 前回の状態）
#                 - 初回実行（キャッシュなし）のときだけ、対象期間の全便を一覧で 1 回通知する
#
#                 【変更として扱うもの】（便名 + 日付で照合）
#                 - 🔔 時刻・状態の変更: 予定時刻 / 最新時刻（見込み・実績）/ 状態（遅延・出発・到着・欠航）
#                 - 🆕 追加: 前回すでに監視していた日付に、新しい便が現れた
#                 - 🗑️ 削除: 監視中の日付から便が消えた（.env の ICN_NOTIFY_REMOVED=0 で通知しない）
#                 - 🔔 日付変更: 同じ便名で「削除」と「追加」が前後 1 日以内に同時に起きた場合は 1 件にまとめる
#
#                 【変更として扱わないもの】
#                 - 監視期間が 1 日進んだことで新しく見えるようになった便 / 期間外に出た便
#                 - 取得に失敗した日付の便（前回データを持ち越し、次回あらためて比較する）
#                 - 駐機場・ターミナルの割当
#                 - すでに出発/到着済み・欠航の便がサイトから消えた場合
# @attention      プロジェクトのコーディングフォーマット・コメントフォーマット遵守
#                 Windows Task Schedulerで1時間ごとに実行される想定
#                 last_data_cache.jsonとlast_data_cache_arrival.jsonに前回データを保存
#                 （キャッシュの読み書きはこのスクリプトだけが行う。daily_notify.py は触らない）
# @par            History
#                 v1.00 (2025/11/01) - 初期実装・NaN値正規化対応
#                 v1.01 (2025/11/01) - 到着便データ取得・変更検出機能追加
#                 v1.02 (2025/11/04) - 変更データのみ通知機能追加
#                 v1.03 (2025/11/04) - 通知フィルタリング（新規・時間変更のみ）
#                 v1.04 (2025/11/06) - 実際の時間変更検出強化（予定時間不問）
#                 v1.05 (2025/11/08) - 実際の時間変更検出修正（便名・日付のみで照合）
#                 v1.06 (2026/11/08) - コメントフォーマットの統一
#                 v1.07 (2026/11/11) - 通知フォーマットを Changi 通知に完全準拠
#                                      （出発便・到着便を 1 メッセージに統合、全便を載せて変化した便に印を付ける）
#                 v2.00 (2026/11/12) - 全面改修
#                                      ・変更があった便を 1 便 = 1 メッセージで個別通知
#                                      ・変更判定を「予定時刻・最新時刻・状態」の比較に変更（状態だけの変化も検出）
#                                      ・追加 / 削除 / 日付変更の検出（監視期間のずれ・取得失敗では誤検出しない）
#                                      ・監視期間を「前日〜6 日後」に拡大（日付をまたいだ出発・到着を拾う）
#                                      ・通知に失敗した便は前回データを残し、次回もう一度通知する
#                                      ・キャッシュ形式を変更（監視済みの日付を一緒に保存。旧形式も読み込み可）
# Copyright (c) 2025-2026. All Rights reserved.
#
# -----------------------------------------------------------------------------------#

# スクレイピングモジュール
from incheon_cargo_scraper import IncheonCargoScraper  # 仁川空港 貨物便スクレイパー

# 標準ライブラリ
from datetime import datetime, timedelta           # 日付・時刻処理
import sys                                         # 終了コード
import os                                          # 環境変数アクセス
import json                                        # JSON 入出力
import math                                        # NaN 判定
from pathlib import Path                           # パス操作

# 外部ライブラリ
from dotenv import load_dotenv                     # .env 読み込み

# .envファイルを読み込む
load_dotenv()


# ======================================================================================#
# ファイル・パス設定
# ======================================================================================#
# logディレクトリを作成
LOG_DIR = Path(__file__).parent / 'log'            # ログ・キャッシュ保存フォルダ
if not LOG_DIR.exists():
    LOG_DIR.mkdir()

# 前回データを保存するファイル
CACHE_FILE = LOG_DIR / 'last_data_cache.json'                   # 出発便キャッシュ
CACHE_FILE_ARRIVAL = LOG_DIR / 'last_data_cache_arrival.json'   # 到着便キャッシュ

# ======================================================================================#
# 監視設定
# ======================================================================================#
LOOKBACK_DAYS = 1                                  # 何日前から監視するか（日付をまたいだ出発・到着を拾うため前日を含める）
LOOKAHEAD_DAYS = 6                                 # 何日後まで監視するか
MOVE_MAX_DAYS = 1                                  # 「削除 + 追加」を日付変更とみなす日付差の上限（日）
NOTIFY_REMOVED = os.getenv('ICN_NOTIFY_REMOVED', '1').strip().lower() not in ('0', 'false', 'no', 'off')  # 削除を通知するか

# 対象（フライトタイプ, 表示名, キャッシュファイル）
DIRECTIONS = [
    ('departure', '出発便', CACHE_FILE),
    ('arrival', '到着便', CACHE_FILE_ARRIVAL),
]


# ======================================================================================#
# @function name:   clean_records
# @function start
def clean_records(records):
    """
    ----------------------------------------------------------------------
    関数概要：データ行の NaN を None に変換する
    - JSON 保存・比較のため、欠損値の表現を None に統一
    ----------------------------------------------------------------------
    Args:
        - records -> list[dict] --- データ行のリスト（DataFrame.to_dict('records') の結果）
    ----------------------------------------------------------------------
    Returns:
        - cleaned -> list[dict] --- NaN を None に置き換えたデータ行のリスト
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v2.00 (2026/11/12) - 新規作成（保存処理に埋め込まれていた変換を共通化）
    ----------------------------------------------------------------------
    """
    return [
        {key: (None if isinstance(value, float) and math.isnan(value) else value) for key, value in item.items()}
        for item in records
    ]


# @function name:   clean_records
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   date_range
# @function start
def date_range(start_date, end_date):
    """
    ----------------------------------------------------------------------
    関数概要：開始日〜終了日の日付文字列（YYYYMMDD）を列挙する
    ----------------------------------------------------------------------
    Args:
        - start_date -> str --- 開始日 (YYYYMMDD)
        - end_date -> str --- 終了日 (YYYYMMDD)
    ----------------------------------------------------------------------
    Returns:
        - dates -> list[str] --- 日付文字列のリスト（変換不能時は空リスト）
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v2.00 (2026/11/12) - 新規作成
    ----------------------------------------------------------------------
    """
    try:
        current = datetime.strptime(str(start_date)[:8], '%Y%m%d')
        end = datetime.strptime(str(end_date)[:8], '%Y%m%d')
    except ValueError:
        return []
    dates = []
    while current <= end:
        dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)
    return dates


# @function name:   date_range
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   load_cache
# @function start
def load_cache(cache_file):
    """
    ----------------------------------------------------------------------
    関数概要：前回取得したデータをキャッシュファイルから読み込む
    - 新形式: {"version": 2, "covered_dates": [...], "flights": [...]}
    - 旧形式（便データのリストのみ）も読み込める。監視済みの日付は
      便データの最小日〜最大日として扱う
    ----------------------------------------------------------------------
    Args:
        - cache_file -> Path --- キャッシュファイルのパス
    ----------------------------------------------------------------------
    Returns:
        - cache -> dict | None --- {'flights': list[dict], 'covered_dates': set[str]}
                                   （ファイルが無い・読み込み失敗時は None）
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v1.00 (2025/11/01) - 初期実装（load_previous_data）
        - revision       v2.00 (2026/11/12) - 出発便・到着便で共通化、監視済みの日付を扱う新形式に対応
    ----------------------------------------------------------------------
    """
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"警告: キャッシュファイルの読み込みに失敗 - {e}")
        return None

    if isinstance(data, dict) and isinstance(data.get('flights'), list):
        return {'flights': data['flights'], 'covered_dates': set(data.get('covered_dates') or [])}
    if isinstance(data, list):
        # 旧形式: 便がある日の最小〜最大を監視済みとみなす
        days = sorted(str(item.get('取得日')) for item in data if isinstance(item, dict) and item.get('取得日'))
        covered = set(date_range(days[0], days[-1])) if days else set()
        return {'flights': [item for item in data if isinstance(item, dict)], 'covered_dates': covered}
    print(f"警告: キャッシュファイルの形式が不正です - {cache_file}")
    return None


# @function name:   load_cache
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   save_cache
# @function start
def save_cache(cache_file, flights, covered_dates):
    """
    ----------------------------------------------------------------------
    関数概要：今回のデータをキャッシュファイルに保存（次回の比較用）
    ----------------------------------------------------------------------
    Args:
        - cache_file -> Path --- キャッシュファイルのパス
        - flights -> list[dict] --- 保存する便データ
        - covered_dates -> set[str] --- 監視済みの日付（YYYYMMDD）
    ----------------------------------------------------------------------
    Returns:
        - success -> bool --- 保存成功時 True
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v1.00 (2025/11/01) - 初期実装（save_current_data）
        - revision       v2.00 (2026/11/12) - 出発便・到着便で共通化、監視済みの日付を一緒に保存
    ----------------------------------------------------------------------
    """
    data = {
        'version': 2,
        'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'covered_dates': sorted(covered_dates),
        'flights': clean_records(flights),
    }
    try:
        # 書き込み途中で止まっても前回データを壊さないよう、一時ファイルに書いてから置き換える
        tmp_file = cache_file.with_name(cache_file.name + '.tmp')
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, cache_file)
        print(f"  データをキャッシュに保存: {cache_file}")
        return True
    except Exception as e:
        print(f"警告: キャッシュファイルの保存に失敗 - {e}")
        return False


# @function name:   save_cache
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   index_flights
# @function start
def index_flights(flights, flight_type):
    """
    ----------------------------------------------------------------------
    関数概要：便データを照合キー（便名, 日付, 連番）で引ける辞書にする
    - 連番は同じ日に同じ便名が複数ある場合の区別用（予定時刻順に 0, 1, ...）
    ----------------------------------------------------------------------
    Args:
        - flights -> list[dict] --- 便データ
        - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
    ----------------------------------------------------------------------
    Returns:
        - index -> dict[tuple, dict] --- {(便名, 日付, 連番): データ行}
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v2.00 (2026/11/12) - 新規作成
    ----------------------------------------------------------------------
    """
    sched_key = '出発時間（予定）' if flight_type == 'departure' else '到着時間（予定）'
    index = {}
    counts = {}
    for item in sorted(flights, key=lambda r: (str(r.get('取得日') or ''), str(r.get(sched_key) or ''))):
        base = (str(item.get('便名') or '').strip(), str(item.get('取得日') or '').strip())
        n = counts.get(base, 0)
        counts[base] = n + 1
        index[(base[0], base[1], n)] = item
    return index


# @function name:   index_flights
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   compare_data
# @function start
def compare_data(previous, current, window_dates, failed_dates, flight_type):
    """
    ----------------------------------------------------------------------
    関数概要：前回データと今回データを比較して、変更があった便を検出する
    - 同じ便（便名 + 日付）: 予定時刻・最新時刻・状態のどれかが違えば「変更」
    - 今回だけにある便: 前回すでに監視していた日付なら「追加」
                        （監視期間が進んで見えるようになっただけの便は対象外）
    - 前回だけにある便: 取得に失敗した日付 → 持ち越し（通知しない）
                        監視期間の外に出た → 何もしない
                        それ以外 → 「削除」（出発/到着済み・欠航の便は対象外）
    - 同じ便名の「削除」と「追加」が前後 MOVE_MAX_DAYS 日以内にあれば「日付変更」にまとめる
    ----------------------------------------------------------------------
    Args:
        - previous -> dict | None --- 前回のキャッシュ（load_cache の戻り値。None は初回）
        - current -> list[dict] --- 今回取得したデータ
        - window_dates -> list[str] --- 今回の監視期間の日付（YYYYMMDD）
        - failed_dates -> set[str] --- 今回取得に失敗した日付
        - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
    ----------------------------------------------------------------------
    Returns:
        - (changes, carried) -> tuple[list[dict], dict] ---
              changes: 変更情報のリスト（flight_type / kind / key / row / prev / prev_key）
              carried: 取得失敗のため前回データを持ち越す便 {照合キー: データ行}
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v1.05 (2025/11/08) - 実際の時間変更検出修正（便名・日付のみで照合）
        - revision       v2.00 (2026/11/12) - 全面改修（状態の変化・追加・削除・日付変更を検出、
                                              監視期間のずれと取得失敗による誤検出を防止）
    ----------------------------------------------------------------------
    """
    if previous is None:
        return [], {}

    signature = IncheonCargoScraper.flight_signature
    prev_index = index_flights(previous['flights'], flight_type)
    curr_index = index_flights(current, flight_type)
    prev_covered = previous['covered_dates']
    window = set(window_dates)

    changes = []
    carried = {}

    # 今回ある便: 変更 / 追加
    for key, row in curr_index.items():
        if key in prev_index:
            prev_row = prev_index[key]
            if signature(prev_row, flight_type) != signature(row, flight_type):
                changes.append({'flight_type': flight_type, 'kind': 'changed', 'key': key, 'row': row, 'prev': prev_row})
        elif key[1] in prev_covered:
            changes.append({'flight_type': flight_type, 'kind': 'new', 'key': key, 'row': row, 'prev': None})

    # 前回だけにある便: 持ち越し / 削除
    for key, prev_row in prev_index.items():
        if key in curr_index:
            continue
        if key[1] in failed_dates:
            carried[key] = prev_row
        elif key[1] in window and NOTIFY_REMOVED:
            phase = IncheonCargoScraper.flight_state(prev_row, flight_type)['phase']
            if phase not in ('done', 'cancelled'):
                changes.append({'flight_type': flight_type, 'kind': 'removed', 'key': key, 'row': prev_row, 'prev': None})

    # 同じ便名の「削除」+「追加」（日付差 MOVE_MAX_DAYS 以内）は「日付変更」1 件にまとめる
    for removed in [c for c in changes if c['kind'] == 'removed']:
        best = None
        for added in [c for c in changes if c['kind'] == 'new' and c['key'][0] == removed['key'][0]]:
            try:
                gap = abs((datetime.strptime(added['key'][1], '%Y%m%d') - datetime.strptime(removed['key'][1], '%Y%m%d')).days)
            except ValueError:
                continue
            if gap <= MOVE_MAX_DAYS and (best is None or gap < best[0]):
                best = (gap, added)
        if best:
            added = best[1]
            added.update({'kind': 'moved', 'prev': removed['row'], 'prev_key': removed['key']})
            changes.remove(removed)

    changes.sort(key=lambda c: (c['key'][1], c['key'][0]))
    return changes, carried


# @function name:   compare_data
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   describe_change
# @function start
def describe_change(change):
    """
    ----------------------------------------------------------------------
    関数概要：変更情報をログ表示用の 1 行にする
    - 例: [変更] K4217 (20261113) 予定 11:35 / 最新 - / scheduled → 予定 11:35 / 最新 17:05 / delayed
    ----------------------------------------------------------------------
    Args:
        - change -> dict --- compare_data が返した変更情報
    ----------------------------------------------------------------------
    Returns:
        - text -> str --- ログ表示用文字列
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v2.00 (2026/11/12) - 新規作成
    ----------------------------------------------------------------------
    """
    def brief(row):
        sig = IncheonCargoScraper.flight_signature(row, change['flight_type'])
        return f"予定 {sig[0] or '-'} / 最新 {sig[1] or '-'} / {sig[2]}{' ' + sig[3] if sig[3] else ''}"

    label = {'changed': '変更', 'new': '追加', 'removed': '削除', 'moved': '日付変更'}[change['kind']]
    flight, day = change['key'][0], change['key'][1]
    if change['kind'] == 'changed':
        return f"[{label}] {flight} ({day}) {brief(change['prev'])} → {brief(change['row'])}"
    if change['kind'] == 'moved':
        return f"[{label}] {flight} ({change['prev_key'][1]}) {brief(change['prev'])} → ({day}) {brief(change['row'])}"
    return f"[{label}] {flight} ({day}) {brief(change['row'])}"


# @function name:   describe_change
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   build_cache_flights
# @function start
def build_cache_flights(current, carried, failed_changes, flight_type):
    """
    ----------------------------------------------------------------------
    関数概要：次回の比較に使う便データ（キャッシュに保存する内容）を組み立てる
    - 基本は今回取得したデータ
    - 取得に失敗した日付の便は前回データを持ち越す
    - 通知に失敗した変更は「前回の状態」に戻しておき、次回もう一度検出・通知されるようにする
    ----------------------------------------------------------------------
    Args:
        - current -> list[dict] --- 今回取得したデータ
        - carried -> dict --- 持ち越す便 {照合キー: データ行}
        - failed_changes -> list[dict] --- 通知に失敗した変更情報
        - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
    ----------------------------------------------------------------------
    Returns:
        - flights -> list[dict] --- キャッシュに保存する便データ
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v2.00 (2026/11/12) - 新規作成
    ----------------------------------------------------------------------
    """
    saved = index_flights(current, flight_type)
    saved.update(carried)
    for change in failed_changes:
        kind, key = change['kind'], change['key']
        if kind == 'changed':
            saved[key] = change['prev']                  # 前回の状態に戻す
        elif kind == 'new':
            saved.pop(key, None)                         # まだ無かったことにする
        elif kind == 'removed':
            saved[key] = change['row']                   # まだ在ることにする
        elif kind == 'moved':
            saved.pop(key, None)
            saved[change['prev_key']] = change['prev']
    return list(saved.values())


# @function name:   build_cache_flights
# @function end
# ======================================================================================#


# ======================================================================================#
# @function name:   main
# @function start
def main():
    """
    ----------------------------------------------------------------------
    関数概要：メイン処理 - 1時間ごとのチェック
    - 前日〜6 日後のデータ（出発便・到着便）を取得
    - 前回データと比較
    - 変更があった便だけを 1 便 = 1 メッセージで Discord に個別通知
    - 初回実行（キャッシュなし）は対象期間の全便を一覧で 1 回通知
    ----------------------------------------------------------------------
    Args:
        - なし
    ----------------------------------------------------------------------
    Returns:
        なし (終了コードをsys.exitで返す。0 = 正常 / 1 = 取得失敗または通知失敗あり)
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v1.01 (2025/11/01) - 到着便対応追加
        - revision       v1.07 (2026/11/11) - 通知を Changi 通知と同一フォーマットに変更
        - revision       v2.00 (2026/11/12) - 変更があった便の個別通知に変更
    ----------------------------------------------------------------------
    """

    # .envファイルから環境変数を取得
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

    if not webhook_url:
        print("エラー: 環境変数 DISCORD_WEBHOOK_URL が設定されていません")
        print("\n.envファイルを作成して以下の内容を記載してください:")
        print("  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...")
        sys.exit(1)

    # 日付を計算（前日〜6 日後）
    today = datetime.now()
    start_date = (today - timedelta(days=LOOKBACK_DAYS)).strftime('%Y%m%d')
    end_date = (today + timedelta(days=LOOKAHEAD_DAYS)).strftime('%Y%m%d')
    window_dates = date_range(start_date, end_date)

    print("=" * 60)
    print("【1時間ごとチェック】仁川国際空港 貨物スケジュール")
    print("=" * 60)
    print(f"実行日時: {today.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"期間: {start_date} ~ {end_date}")
    print(f"空港: NGO (名古屋)")
    print("=" * 60)

    # スクレイパーを初期化
    scraper = IncheonCargoScraper()

    # 出発便・到着便のデータを取得
    current_data = {}                              # フライトタイプ → 今回のデータ
    failed_dates = {}                              # フライトタイプ → 取得に失敗した日付
    dataframes = {}                                # フライトタイプ → DataFrame（初回の一覧通知用）
    for flight_type, label, _ in DIRECTIONS:
        print(f"\n【{label}データ取得】")
        print("=" * 60)
        df = scraper.scrape_multiple_dates(
            start_date=start_date,
            end_date=end_date,
            airport='NGO',
            output_format=None,
            flight_type=flight_type
        )
        dataframes[flight_type] = df
        current_data[flight_type] = clean_records(df.to_dict('records')) if df is not None and len(df) > 0 else []
        failed_dates[flight_type] = set(scraper.last_failed_dates.get(flight_type, set()))

    # 全日付・全方向で取得に失敗した場合は何もせず終了（キャッシュは触らない）
    if all(failed_dates[flight_type] >= set(window_dates) for flight_type, _, _ in DIRECTIONS):
        print("\n! データが取得できませんでした")
        sys.exit(1)

    # 前回データとの比較
    previous_data = {}                             # フライトタイプ → 前回のキャッシュ
    carried_data = {}                              # フライトタイプ → 持ち越す便
    all_changes = []                               # 全方向の変更情報
    for flight_type, label, cache_file in DIRECTIONS:
        print(f"\n【{label}】前回データとの比較中...")
        previous = load_cache(cache_file)
        previous_data[flight_type] = previous
        changes, carried = compare_data(previous, current_data[flight_type], window_dates, failed_dates[flight_type], flight_type)
        carried_data[flight_type] = carried
        all_changes.extend(changes)
        if previous is None:
            print(f"{label}比較結果: 前回データなし（今回のデータを基準として保存）")
        elif changes:
            print(f"{label}比較結果: 変更 {len(changes)}件")
            for change in changes:
                print(f"  {describe_change(change)}")
        else:
            print(f"{label}比較結果: 変更なし")
        if carried:
            print(f"  取得失敗のため前回データを持ち越し: {len(carried)}件")

    # 初回実行（出発便・到着便ともキャッシュなし）: 全便を一覧で 1 回通知して基準データを保存
    if all(previous_data[flight_type] is None for flight_type, _, _ in DIRECTIONS):
        has_flights = any(current_data[flight_type] for flight_type, _, _ in DIRECTIONS)
        if has_flights:
            print("\n初回実行のため、対象期間の全便を一覧で通知します...")
            success = scraper.send_discord_notification(
                dataframes['departure'], dataframes['arrival'], start_date, end_date, 'NGO'
            )
        else:
            print("\n初回実行ですが対象期間に便がないため、通知せず基準データだけ保存します")
            success = True
        if not success:
            print("\n! Discord通知に失敗しました")
            sys.exit(1)
        for flight_type, _, cache_file in DIRECTIONS:
            save_cache(cache_file, current_data[flight_type], set(window_dates) - failed_dates[flight_type])
        print("\n" + "=" * 60)
        print("✓ 初回実行: 基準データを保存しました")
        print("=" * 60)
        sys.exit(0)

    # 変更があった便を個別に通知
    failed_changes = []
    if all_changes:
        print(f"\n変更が検出されました。Discordに個別通知を送信します...（{len(all_changes)}件）")
        results = scraper.send_change_notifications(all_changes, 'NGO')
        failed_changes = [change for change, ok in zip(all_changes, results) if not ok]
    else:
        print("\n変更がないため、通知をスキップします")

    # 今回のデータを保存（次回比較用）
    for flight_type, _, cache_file in DIRECTIONS:
        previous = previous_data[flight_type]
        # 監視済みの日付 = 今回取得できた日付 + 取得に失敗したが前回は監視済みだった日付
        covered = set(window_dates) - failed_dates[flight_type]
        if previous is not None:
            covered |= failed_dates[flight_type] & previous['covered_dates']
        flights = build_cache_flights(
            current_data[flight_type],
            carried_data[flight_type],
            [change for change in failed_changes if change['flight_type'] == flight_type],
            flight_type
        )
        save_cache(cache_file, flights, covered)

    print("\n" + "=" * 60)
    if failed_changes:
        print(f"! 通知に失敗した変更が {len(failed_changes)}件あります（次回のチェックで再通知します）")
        print("=" * 60)
        sys.exit(1)
    if all_changes:
        print(f"✓ 変更を検出し、{len(all_changes)}件を個別に通知しました")
    else:
        print("✓ チェック完了（変更なし）")
    print("=" * 60)
    sys.exit(0)


# @function name:   main
# @function end
# ======================================================================================#


if __name__ == '__main__':
    main()
