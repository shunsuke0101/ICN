# coding: utf-8
# -----------------------------------------------------------------------------------#
# @file           ICN/incheon_cargo_scraper.py
# @brief          仁川国際空港 貨物出発・到着スケジュール スクレイピングシステム
# @author         Kidera Shunsuke
# @date           2025/11/01
# $Version:       4.00
# $Revision:      2026/11/12
# @note           仁川国際空港の貨物出発・到着スケジュールをWebスクレイピング
#                 Discord Webhook通知機能を含む
# @attention      プロジェクトのコーディングフォーマット・コメントフォーマット遵守
#                 出発便APIエンドポイント: https://www.airport.kr/depCargo/ap_ja/depCargoSchList.do
#                 到着便APIエンドポイント: https://www.airport.kr/arrCargo/ap_ja/arrCargoSchList.do
#                 データ構造: div.data > div.body > div.group > div.row
#                 駐機場: div.jugi、状態: div.state（列番号は出発便 col5/col6・到着便 col6/col7 と異なる）
#                 時刻欄: <strong>最新時刻</strong><span>当初予定</span>（変更なしの便は <strong>予定</strong> のみ）
#                         最新時刻が実績か見込みかは状態欄（出発 / 到着 / 遅延 / 欠航 / 空）で決まる
# @par            History
#                 v1.00 (2025/11/01) - 初期実装・Discord通知機能追加
#                 v1.01 (2025/11/01) - 到着便データ取得機能追加・CSV出力デフォルト無効化
#                 v3.00 (2026/11/08) - Discord 通知を Changi 通知と共通の表形式に変更
#                 v3.01 (2026/11/08) - コメントフォーマットの統一
#                 v3.02 (2026/11/09) - 駐機場をクラス名で取得（到着便の列ずれ修正）・通知に駐機場を表示
#                 v3.03 (2026/11/11) - Discord 通知フォーマットを Changi 通知に完全準拠
#                                      （出発便・到着便を 1 メッセージに統合・見出し／フッター文言・便間の空行）
#                 v4.00 (2026/11/12) - 時刻・状態の判定を全面見直し
#                                      ・最新時刻を「実績」と決めつけず、状態欄から 実績 / 見込み を判定（flight_state）
#                                        （遅延・時刻変更の便が「出発済み」と表示されていた不具合を解消）
#                                      ・日またぎ（予定 00:05 → 実績 前日 23:51 など）の日付を補正し、名古屋側の推定時刻を修正
#                                      ・列名 '出発時間（実際）' / '到着時間（実際）' を '…（最新）' に変更
#                                      ・変更があった便の個別通知（send_change_notifications）を追加
#                                      ・取得失敗と「該当便なし」を区別（last_failed_dates）
# Copyright (c) 2025-2026. All Rights reserved.
#
# -----------------------------------------------------------------------------------#

"""
========================================================================================
モジュール概要：仁川国際空港 貨物出発・到着スケジュール スクレイピングモジュール
========================================================================================
仁川国際空港（ICN）の貨物出発・到着スケジュールを公式サイトから取得し、
名古屋（NGO）関連便を Discord へ通知します。

主な機能:
    - 出発便・到着便スケジュールの取得（API エンドポイント + フォールバック）
    - 複数日のデータ取得（並列）
    - CSV/JSON/Excel 形式でのエクスポート
    - Discord Webhook 通知（Changi / 香港 / 上海 の通知と共通のフォーマット）
      - 一覧通知: send_discord_notification（出発便・到着便を 1 メッセージ）
      - 個別通知: send_change_notifications（変更があった便を 1 便 = 1 メッセージ）
========================================================================================
"""

# 外部ライブラリ
import requests                                    # HTTP 通信
from bs4 import BeautifulSoup                      # HTML パース
import pandas as pd                                # 表データ処理

# 標準ライブラリ
from datetime import datetime, timedelta, timezone  # 日付・時刻処理
import time                                        # 待機
import json                                        # JSON 入出力
from concurrent.futures import ThreadPoolExecutor  # 並列リクエスト
from urllib.parse import urlencode                 # URL エンコード
import re                                          # 正規表現
import os                                          # 環境変数アクセス

# 外部ライブラリ
from dotenv import load_dotenv                     # .env 読み込み

# .envファイルを読み込む
load_dotenv()


class IncheonCargoScraper:
    """
    ========================================================================================
    クラス概要：仁川国際空港の貨物スケジュールをスクレイピングするクラス
    ========================================================================================
    仁川国際空港の公式サイトから貨物便スケジュールを取得し、Discord へ通知します。

    主な機能:
        - 貨物出発・到着スケジュールの取得
        - 複数日のデータ取得
        - CSV/JSON/Excel形式でのエクスポート
        - Discord Webhook通知

    Attributes:
        - dep_api_url / arr_api_url -> str --- 出発便・到着便の API エンドポイント
        - dep_base_url / arr_base_url -> str --- フォールバック用ページ URL
        - discord_webhook_url -> str | None --- Discord Webhook URL
        - headers -> dict --- HTTP リクエストヘッダー
        - session -> requests.Session --- HTTP セッション

    使用例:
        >>> scraper = IncheonCargoScraper()
        >>> df_dep = scraper.scrape_multiple_dates('20251101', '20251107', airport='NGO', flight_type='departure')
        >>> df_arr = scraper.scrape_multiple_dates('20251101', '20251107', airport='NGO', flight_type='arrival')
        >>> scraper.send_discord_notification(df_dep, df_arr, '20251101', '20251107')
    ========================================================================================
    """
    
    # ======================================================================================#
    # @function name:   __init__
    # @function start
    def __init__(self, discord_webhook_url=None):
        """
        ----------------------------------------------------------------------
        関数概要：コンストラクタ
        - APIエンドポイントとヘッダーを設定
        - Discord Webhook URLを初期化
        ----------------------------------------------------------------------
        Args:
            - discord_webhook_url -> str --- Discord Webhook URL（省略可）
        ----------------------------------------------------------------------
        Returns:
            - なし
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v1.01 (2025/11/01) - 到着便対応追加
            - revision       v4.00 (2026/11/12) - last_failed_dates を追加
        ----------------------------------------------------------------------
        """
        # 実際のAPIエンドポイント（encパラメータをデコードして取得）
        self.dep_api_url = "https://www.airport.kr/depCargo/ap_ja/depCargoSchList.do"
        self.arr_api_url = "https://www.airport.kr/arrCargo/ap_ja/arrCargoSchList.do"
        self.dep_base_url = "https://www.airport.kr/ap_ja/1787/subview.do"
        self.arr_base_url = "https://www.airport.kr/ap_ja/1790/subview.do"
        self.discord_webhook_url = discord_webhook_url or os.getenv('DISCORD_WEBHOOK_URL')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.airport.kr/'
        }
        self.session = requests.Session()
        # 直近の scrape_multiple_dates で取得に失敗した日付（flight_type → set[YYYYMMDD]）
        self.last_failed_dates = {'departure': set(), 'arrival': set()}

    # @function name:   __init__
    # @function end
    # ======================================================================================#
    
    # ======================================================================================#
    # @function name:   build_params
    # @function start
    def build_params(self, date_str=None, airport='NGO', start_time='0000', end_time='2359', flight_type='departure'):
        """
        ----------------------------------------------------------------------
        関数概要：APIリクエストのパラメータを構築
        - 日付、空港、時刻範囲を指定してパラメータ辞書を生成
        ----------------------------------------------------------------------
        Args:
            - date_str -> str --- 日付 (YYYYMMDD形式)。Noneの場合は今日
            - airport -> str --- 空港コード (デフォルト: NGO - 名古屋)
            - start_time -> str --- 開始時刻 (HHMM形式)
            - end_time -> str --- 終了時刻 (HHMM形式)
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
        ----------------------------------------------------------------------
        Returns:
            - params -> dict --- APIリクエストパラメータ
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ----------------------------------------------------------------------
        """
        if date_str is None:
            date_str = datetime.now().strftime('%Y%m%d')
        
        tomorrow = (datetime.strptime(date_str, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
        current_time = datetime.now().strftime('%H%M')
        
        # パラメータを構築
        params = {
            'curDate': date_str,
            'startTime': start_time,
            'airPort': airport,
            'endTime': end_time,
            'todayDate': date_str,
            'tomorrowDate': tomorrow,
            'todayTime': current_time,
            'curStime': start_time,
            'curEtime': end_time,
            'siteId': 'ap_ja',
            'langSe': 'ja',
            'scheduleListLength': '2',
            'termId': '',
            'daySel': date_str,
            'fromTime': start_time,
            'toTime': end_time,
            'airport': airport,
            'airline': '',
            'airplane': ''
        }
        
        return params

    # @function name:   build_params
    # @function end
    # ======================================================================================#
    
    # ======================================================================================#
    # @function name:   fetch_page
    # @function start
    def fetch_page(self, params, flight_type='departure'):
        """
        ----------------------------------------------------------------------
        関数概要：ページを取得する（APIエンドポイント使用）
        - APIエンドポイントにリクエストを送信
        - レスポンスをBeautifulSoupでパース
        ----------------------------------------------------------------------
        Args:
            - params -> dict --- リクエストパラメータ
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
        ----------------------------------------------------------------------
        Returns:
            - soup -> BeautifulSoup | None --- パースされたHTML（取得失敗時は None）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ----------------------------------------------------------------------
        """
        try:
            # フライトタイプに応じてURLを選択
            api_url = self.dep_api_url if flight_type == 'departure' else self.arr_api_url
            base_url = self.dep_base_url if flight_type == 'departure' else self.arr_base_url
            
            # まずAPIエンドポイントを試す
            response = self.session.get(api_url, params=params, headers=self.headers, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # データが見つからない場合、別のエンドポイントを試す
            if '照会されたデータがありません' in response.text or 'there is no registered data' in response.text.lower():
                print("  APIエンドポイントにデータがありません。別の方法を試します...")
                
                # iframeやサブビューのURLを試す
                alt_params = params.copy()
                response = self.session.get(base_url, params=alt_params, headers=self.headers, timeout=30)
                response.raise_for_status()
                response.encoding = 'utf-8'
                soup = BeautifulSoup(response.text, 'html.parser')
            
            return soup
            
        except requests.exceptions.RequestException as e:
            print(f"エラー: ページの取得に失敗しました - {e}")
            return None

    # @function name:   fetch_page
    # @function end
    # ======================================================================================#
    
    # ======================================================================================#
    # @function name:   parse_cargo_table
    # @function start
    def parse_cargo_table(self, soup, flight_type='departure'):
        """
        ----------------------------------------------------------------------
        関数概要：貨物スケジュールテーブルをパース
        - HTMLからdiv.data構造を解析
        - フライト情報を抽出してリスト化
        ----------------------------------------------------------------------
        Args:
            - soup -> BeautifulSoup --- パースされたHTML
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
        ----------------------------------------------------------------------
        Returns:
            - flights -> list --- 貨物情報のリスト（辞書形式）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v1.01 (2025/11/01) - 到着便対応追加
            - revision       v3.02 (2026/11/09) - 駐機場・状態をクラス名（jugi / state）で取得
            - revision       v4.00 (2026/11/12) - 時刻欄を「予定」「最新」として取得（旧: 最新時刻を「実際」として取得）
        ----------------------------------------------------------------------
        """
        cargo_data = []
        
        print("  HTML解析中...")
        
        # 出発便か到着便かでキー名を設定
        time_key_scheduled = '出発時間（予定）' if flight_type == 'departure' else '到着時間（予定）'
        time_key_latest = '出発時間（最新）' if flight_type == 'departure' else '到着時間（最新）'
        location_key = '目的地' if flight_type == 'departure' else '出発地'
        status_key = '出発状態' if flight_type == 'departure' else '到着状態'
        
        # 新しい構造: div.data の中の div.row を探す
        data_container = soup.find('div', class_='data')
        
        if data_container:
            print("  ✓ データコンテナを発見")
            
            # ヘッダーを取得
            header_div = data_container.find('div', class_='header')
            headers = []
            if header_div:
                header_cols = header_div.find_all('div', class_='col')
                headers = [col.get_text(strip=True) for col in header_cols]
                print(f"  ヘッダー: {headers}")
            
            # データ行を取得
            body_div = data_container.find('div', class_='body')
            if body_div:
                # 各グループ（フライト情報）を取得
                groups = body_div.find_all('div', class_='group')
                print(f"  見つかったフライト数: {len(groups)}")
                
                for group in groups:
                    # メインの行（toggle）を取得
                    toggle_row = group.find('div', class_='toggle')
                    if toggle_row:
                        row_data = {}
                        
                        # 時間（出発または到着）
                        col1 = toggle_row.find('div', class_='col1')
                        if col1:
                            # 時刻欄の構造（v4.00 で解釈を見直し）:
                            #   変更なし: <strong>予定時刻</strong>
                            #   変更あり: <strong>最新時刻</strong><span>当初の予定時刻</span>
                            # 最新時刻は「実績」とは限らない（遅延・時刻変更の見込み時刻のこともある）。
                            # 実績かどうかは状態欄で決まるため、ここでは「予定」「最新」としてそのまま保持し、
                            # 解釈は flight_state に任せる。
                            time_div = col1.find('div', class_='time') or col1
                            strong_elem = time_div.find('strong')
                            span_elem = time_div.find('span')
                            strong_time = strong_elem.get_text(strip=True) if strong_elem else None
                            span_time = span_elem.get_text(strip=True) if span_elem else None

                            if span_time:
                                row_data[time_key_scheduled] = span_time
                                row_data[time_key_latest] = strong_time if strong_time != span_time else None
                            else:
                                row_data[time_key_scheduled] = strong_time
                                row_data[time_key_latest] = None
                        
                        # 目的地または出発地
                        col2 = toggle_row.find('div', class_='col2')
                        if col2:
                            location_div = col2.find('div', class_='location')
                            if location_div:
                                # hidden-textを除外
                                for hidden in location_div.find_all('i', class_='hidden-text'):
                                    hidden.decompose()
                                
                                # 経由地情報を含むテキストを取得
                                location_text = location_div.get_text(strip=True)
                                row_data[location_key] = location_text
                        
                        # 航空会社/便名
                        col3 = toggle_row.find('div', class_='col3')
                        if col3:
                            airplane_div = col3.find('div', class_='airplane')
                            if airplane_div:
                                # 便名と航空会社名を含む全てのspanを取得
                                name_spans = airplane_div.find_all('span', class_='name')
                                if len(name_spans) >= 2:
                                    # 最初のspanが便名
                                    flight_strong = name_spans[0].find('strong')
                                    if flight_strong:
                                        row_data['便名'] = flight_strong.get_text(strip=True)
                                    
                                    # 2番目のspanが航空会社名
                                    row_data['航空会社'] = name_spans[1].get_text(strip=True)
                                elif len(name_spans) == 1:
                                    # 1つしかない場合はそれを確認
                                    text = name_spans[0].get_text(strip=True)
                                    if text:
                                        # 数字を含む場合は便名、そうでなければ航空会社名
                                        if any(c.isdigit() for c in text):
                                            row_data['便名'] = text
                                        else:
                                            row_data['航空会社'] = text
                        
                        # ターミナル
                        col4 = toggle_row.find('div', class_='col4')
                        if col4:
                            # hidden-textを除外
                            for hidden in col4.find_all('i', class_='hidden-text'):
                                hidden.decompose()
                            terminal = col4.get_text(strip=True)
                            if terminal:
                                row_data['ターミナル'] = terminal
                        
                        # 駐機場（v3.02: 列番号ではなくクラス名で特定）
                        #   出発便は col5、到着便は col6 に入っており列番号が異なるため、
                        #   div.jugi（駐機場）/ div.state（状態）をクラス名で探す。
                        #   見つからない場合は従来の col5 / col6 にフォールバック。
                        stand_div = toggle_row.find('div', class_='jugi') or toggle_row.find('div', class_='col5')
                        if stand_div:
                            # hidden-textを除外
                            for hidden in stand_div.find_all('i', class_='hidden-text'):
                                hidden.decompose()
                            stand = stand_div.get_text(strip=True)
                            if stand:
                                row_data['駐機場'] = stand

                        # 状態（出発または到着）
                        state_div = toggle_row.find('div', class_='state') or toggle_row.find('div', class_='col6')
                        if state_div:
                            # hidden-textを除外
                            for hidden in state_div.find_all('i', class_='hidden-text'):
                                hidden.decompose()
                            status = state_div.get_text(strip=True)
                            if status:
                                row_data[status_key] = status
                        
                        if row_data:
                            cargo_data.append(row_data)
                            print(f"  ✓ フライトデータ追加: {row_data.get('便名', 'N/A')} - {row_data.get(location_key, 'N/A')}")
        
        # 古い構造（テーブル）もチェック
        if not cargo_data:
            print("  新しい構造にデータなし。テーブル構造を確認中...")
            tables = soup.find_all('table')
            print(f"  見つかったテーブル数: {len(tables)}")
            
            for idx, table in enumerate(tables):
                # テーブルヘッダーを確認
                headers = []
                header_row = table.find('thead')
                if header_row:
                    headers = [th.get_text(strip=True) for th in header_row.find_all('th')]
                else:
                    # theadがない場合、最初の行をヘッダーとして使用
                    first_row = table.find('tr')
                    if first_row:
                        headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
                
                if headers:
                    print(f"    テーブル {idx + 1} ヘッダー: {headers}")
                
                # テーブルボディからデータを取得
                tbody = table.find('tbody')
                rows_to_process = []
                
                if tbody:
                    rows_to_process = tbody.find_all('tr')
                else:
                    # tbodyがない場合、すべてのtrを取得（最初の行を除く）
                    all_rows = table.find_all('tr')
                    if len(all_rows) > 1:
                        rows_to_process = all_rows[1:]
                
                for row in rows_to_process:
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        row_data = {}
                        cell_texts = [cell.get_text(strip=True) for cell in cells]
                        
                        if not any(cell_texts):
                            continue
                        
                        if headers:
                            for idx, cell in enumerate(cells):
                                header_name = headers[idx] if idx < len(headers) else f'column_{idx}'
                                cell_text = cell.get_text(strip=True)
                                row_data[header_name] = cell_text
                        else:
                            for idx, cell in enumerate(cells):
                                row_data[f'column_{idx}'] = cell.get_text(strip=True)
                        
                        if row_data:
                            cargo_data.append(row_data)
        
        # データがない場合の処理
        if not cargo_data:
            no_data_msg = soup.find(string=re.compile(r'照会されたデータがありません|データがありません|No data|there is no registered data', re.IGNORECASE))
            if no_data_msg:
                print("  情報: 該当する貨物スケジュールデータがありません")
        
        return cargo_data

    # @function name:   parse_cargo_table
    # @function end
    # ======================================================================================#
    
    # ======================================================================================#
    # @function name:   scrape
    # @function start
    def scrape(self, date_str=None, airport='NGO', output_format=None, save_html=False, flight_type='departure'):
        """
        ----------------------------------------------------------------------
        関数概要：貨物スケジュールをスクレイピング
        - 指定日付・空港のデータを取得
        - オプションでファイル保存
        ----------------------------------------------------------------------
        Args:
            - date_str -> str --- 日付 (YYYYMMDD形式)。Noneの場合は今日
            - airport -> str --- 空港コード (デフォルト: NGO)
            - output_format -> str --- 出力形式 ('csv', 'json', 'excel')
            - save_html -> bool --- HTMLを保存するかどうか
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
        ----------------------------------------------------------------------
        Returns:
            - df -> pd.DataFrame | None --- スクレイピングされたデータ
                                            （該当便なしは空の DataFrame、取得失敗は None）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v1.01 (2025/11/01) - 到着便対応追加
            - revision       v4.00 (2026/11/12) - 「該当便なし」と確認できない空データは取得失敗（None）として返す
        ----------------------------------------------------------------------
        """
        params = self.build_params(date_str, airport, flight_type=flight_type)
        flight_type_ja = '出発' if flight_type == 'departure' else '到着'
        api_url = self.dep_api_url if flight_type == 'departure' else self.arr_api_url
        
        print(f"取得パラメータ: 日付={params['curDate']}, 空港={airport}, タイプ={flight_type_ja}")
        print(f"APIエンドポイント: {api_url}")
        print(f"データを取得中...")
        
        soup = self.fetch_page(params, flight_type)
        if not soup:
            return None
        
        # デバッグ用: HTMLを保存
        if save_html:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            html_filename = f'debug_html_{flight_type}_{timestamp}.html'
            with open(html_filename, 'w', encoding='utf-8') as f:
                f.write(soup.prettify())
            print(f"  デバッグ用HTMLを保存: {html_filename}")
        
        # データをパース
        cargo_data = self.parse_cargo_table(soup, flight_type)
        
        if not cargo_data:
            # v4.00: サイトが「該当便なし」と明示している場合だけ 0 件として扱う。
            #        メンテナンス画面・構造変更などで読めなかった場合は取得失敗（None）にして、
            #        呼び出し側（変更検出）が「便が削除された」と誤判定しないようにする。
            no_data_confirmed = soup.find('div', class_='no-data') is not None or \
                soup.find(string=re.compile(r'照会されたデータがありません|there is no registered data', re.IGNORECASE)) is not None
            if not no_data_confirmed:
                print("警告: スケジュール表を読み取れませんでした（取得失敗として扱います）")
                print("  save_html=True を設定してHTMLを確認することができます")
                return None
            print("情報: 該当する便はありません")
            return pd.DataFrame()
        
        # DataFrameに変換
        df = pd.DataFrame(cargo_data)
        
        # 必須の列が存在することを保証（最新時刻・状態が 1 件も無い日でも列を作成）
        # v3.02: 駐機場・ターミナル列も常に存在させる（未割当日はキャッシュ上 null になる）
        time_key_latest = '出発時間（最新）' if flight_type == 'departure' else '到着時間（最新）'
        status_key = '出発状態' if flight_type == 'departure' else '到着状態'
        for key in (time_key_latest, 'ターミナル', '駐機場', status_key):
            if key not in df.columns:
                df[key] = None

        print(f"\n✓ 取得したデータ: {len(df)} 件")
        
        # データを保存
        if output_format and len(df) > 0:
            self.save_data(df, date_str, airport, output_format)
        
        return df

    # @function name:   scrape
    # @function end
    # ======================================================================================#
    
    # ======================================================================================#
    # @function name:   save_data
    # @function start
    def save_data(self, df, date_str, airport, output_format):
        """
        ----------------------------------------------------------------------
        関数概要：データを保存する
        - CSV/JSON/Excel形式でエクスポート
        - logディレクトリに保存
        ----------------------------------------------------------------------
        Args:
            - df -> pd.DataFrame --- 保存するデータ
            - date_str -> str --- 日付
            - airport -> str --- 空港コード
            - output_format -> str --- 出力形式 ('csv', 'json', 'excel')
        ----------------------------------------------------------------------
        Returns:
            - なし
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v1.00 (2025/11/01) - 初期実装
        ----------------------------------------------------------------------
        """
        # logディレクトリを作成
        log_dir = 'log'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        date_part = date_str if date_str else datetime.now().strftime('%Y%m%d')
        
        if output_format == 'csv':
            filename = os.path.join(log_dir, f'incheon_cargo_{airport}_{date_part}_{timestamp}.csv')
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"CSVファイルを保存しました: {filename}")
        
        elif output_format == 'json':
            filename = os.path.join(log_dir, f'incheon_cargo_{airport}_{date_part}_{timestamp}.json')
            df.to_json(filename, orient='records', force_ascii=False, indent=2)
            print(f"JSONファイルを保存しました: {filename}")
        
        elif output_format == 'excel':
            filename = f'incheon_cargo_{airport}_{date_part}_{timestamp}.xlsx'
            df.to_excel(filename, index=False, engine='openpyxl')
            print(f"Excelファイルを保存しました: {filename}")

    # @function name:   save_data
    # @function end
    # ======================================================================================#
    
    # ======================================================================================#
    # @function name:   scrape_multiple_dates
    # @function start
    def scrape_multiple_dates(self, start_date, end_date, airport='NGO', output_format=None, flight_type='departure'):
        """
        ----------------------------------------------------------------------
        関数概要：複数日のデータをスクレイピング
        - 指定期間のデータを日ごとに取得
        - 結果を結合して返す
        ----------------------------------------------------------------------
        Args:
            - start_date -> str --- 開始日 (YYYYMMDD形式)
            - end_date -> str --- 終了日 (YYYYMMDD形式)
            - airport -> str --- 空港コード (デフォルト: NGO)
            - output_format -> str --- 出力形式 ('csv', 'json', 'excel')
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
        ----------------------------------------------------------------------
        Returns:
            - df -> pd.DataFrame --- 結合されたデータ
                                     （取得に失敗した日付は self.last_failed_dates[flight_type] に入る）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v1.01 (2025/11/01) - 到着便対応追加
            - revision       v4.00 (2026/11/12) - 取得に失敗した日付を last_failed_dates に記録
        ----------------------------------------------------------------------
        """
        all_data = []

        start = datetime.strptime(start_date, '%Y%m%d')
        end = datetime.strptime(end_date, '%Y%m%d')
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime('%Y%m%d'))
            current += timedelta(days=1)

        # v3.00: 日付ごとの取得を並列化（最大 3 同時）。従来の「1 日ごとに 2 秒待機」は廃止
        def _one(date_str):
            try:
                return date_str, self.scrape(date_str, airport, output_format=None, save_html=False, flight_type=flight_type)
            except Exception as e:  # noqa: BLE001
                print(f"  [{date_str}] 取得失敗: {e}")
                return date_str, None

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=min(3, len(dates))) as ex:
            results = list(ex.map(_one, dates))
        print(f"\n{len(dates)} 日分を {time.perf_counter() - t0:.1f} 秒で取得")

        # v4.00: 取得失敗（None）の日付を記録（「該当便なし」の空 DataFrame とは区別する）
        failed_dates = {date_str for date_str, df in results if df is None}
        self.last_failed_dates[flight_type] = failed_dates
        if failed_dates:
            print(f"! 取得に失敗した日付: {', '.join(sorted(failed_dates))}")

        for date_str, df in results:
            if df is not None and len(df) > 0:
                df['取得日'] = date_str
                all_data.append(df)
        
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            print(f"\n合計 {len(combined_df)} 件のデータを取得しました")
            
            if output_format:
                self.save_data(combined_df, f"{start_date}_to_{end_date}", airport, output_format)
            
            return combined_df
        else:
            print("データが見つかりませんでした")
            return pd.DataFrame()

    # @function name:   scrape_multiple_dates
    # @function end
    # ======================================================================================#
    
    # ======================================================================================#
    # 表示フォーマット設定（Changi 通知と共通の表形式）
    # ======================================================================================#
    # 名古屋側時刻の推定に使う標準所要時間（分）。.env の FLIGHT_MINUTES_ICN_NGO / NGO_ICN で変更可
    FLIGHT_MIN_ICN_NGO = int(os.getenv('FLIGHT_MINUTES_ICN_NGO', '115'))  # ICN→NGO 所要時間（分）
    FLIGHT_MIN_NGO_ICN = int(os.getenv('FLIGHT_MINUTES_NGO_ICN', '125'))  # NGO→ICN 所要時間（分）
    WEEKDAY_JA = "月火水木金土日"                                          # 曜日表記（weekday() のインデックス順）
    JST = timezone(timedelta(hours=9), 'JST')                              # 日本時間（韓国時間と同じ UTC+9。tzdata 不要の固定オフセット）

    # 最新時刻（HH:MM のみ）の日付を決めるときの許容幅（分）。
    # 予定より LATE_MAX_MIN を超えて遅く見える時刻は前日、EARLY_MAX_MIN を超えて早く見える時刻は翌日とみなす
    EARLY_MAX_MIN = 6 * 60                                                 # 早発・早着として扱う上限（6 時間）
    LATE_MAX_MIN = 18 * 60                                                 # 遅延として扱う上限（18 時間）

    # 状態欄の判定キーワード（日本語サイトの表記 + 韓国語・英語サイトの表記。英語は小文字で比較）
    STATUS_CANCELLED = ('欠航', '결항', 'cancel')                          # 欠航
    STATUS_DELAYED = ('遅延', '지연', 'delay')                             # 遅延（まだ出発/到着していない）
    STATUS_DONE_DEP = ('出発', '출발', 'depart')                           # 出発済み
    STATUS_DONE_ARR = ('到着', '도착', 'arriv', '着陸', '착륙', 'land')    # 到着済み

    # ======================================================================================#
    # @function name:   _color
    # @function start
    @staticmethod
    def _color(env_name, default):
        """
        ----------------------------------------------------------------------
        関数概要：環境変数から埋め込みの色（16 進）を取得する
        ----------------------------------------------------------------------
        Args:
            - env_name -> str --- 環境変数名
            - default -> int --- 未設定・不正時の既定値
        ----------------------------------------------------------------------
        Returns:
            - color -> int --- 色コード
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        v = (os.getenv(env_name) or '').strip().lstrip('#')
        try:
            return int(v, 16) if v else default
        except ValueError:
            return default

    # @function name:   _color
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _is_str
    # @function start
    @staticmethod
    def _is_str(v):
        """
        ----------------------------------------------------------------------
        関数概要：有効な文字列値かどうかを判定する
        - 空文字・'N/A'・'nan'・'None'・'未定' は無効扱い
        ----------------------------------------------------------------------
        Args:
            - v -> Any --- 判定対象
        ----------------------------------------------------------------------
        Returns:
            - is_valid -> bool --- 有効な文字列ならば True
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        return isinstance(v, str) and v.strip() not in ('', 'N/A', 'nan', 'None', '未定')

    # @function name:   _is_str
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _flight_code
    # @function start
    @staticmethod
    def _flight_code(fn):
        """
        ----------------------------------------------------------------------
        関数概要：航空会社コードと便名の間にスペースを入れた表示用便名を返す
        - 例: 'K4219' → 'K4 219'、'JL6749' → 'JL 6749'
        ----------------------------------------------------------------------
        Args:
            - fn -> str --- 便名
        ----------------------------------------------------------------------
        Returns:
            - code -> str --- 表示用便名（便名無しは '?'）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        fn = (fn or '?').strip().replace(' ', '')
        m = re.match(r'^([A-Z][A-Z0-9]|[0-9][A-Z])(\d{1,5}[A-Z]?)$', fn.upper())
        return f"{m.group(1)} {m.group(2)}" if m else fn

    # @function name:   _flight_code
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _parse_hhmm
    # @function start
    @staticmethod
    def _parse_hhmm(date_str, hhmm):
        """
        ----------------------------------------------------------------------
        関数概要：日付文字列と HH:MM を含む文字列から datetime を生成する
        - 例: '20261108' + '22:00' → datetime
        - 韓国・日本は同じ UTC+9 なので時差換算不要
        ----------------------------------------------------------------------
        Args:
            - date_str -> str --- 対象日（YYYYMMDD）
            - hhmm -> str --- HH:MM を含む文字列
        ----------------------------------------------------------------------
        Returns:
            - datetime -> datetime | None --- 変換結果（変換不能時は None）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        if not date_str or not IncheonCargoScraper._is_str(hhmm):
            return None
        m = re.search(r'(\d{1,2}):(\d{2})', hhmm)
        if not m:
            return None
        try:
            return datetime.strptime(f"{date_str[:8]} {int(m.group(1)):02d}:{m.group(2)}", "%Y%m%d %H:%M")
        except ValueError:
            return None

    # @function name:   _parse_hhmm
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _day_label
    # @function start
    def _day_label(self, date_str, today):
        """
        ----------------------------------------------------------------------
        関数概要：日付文字列を相対表記付きのラベルに整形する
        - 例: '今日 11/08 (日)' / '明日 11/09 (月)' / '11/12 (木)'
        ----------------------------------------------------------------------
        Args:
            - date_str -> str --- 対象日（YYYYMMDD）
            - today -> date --- 基準日
        ----------------------------------------------------------------------
        Returns:
            - label -> str --- 整形後ラベル（変換不能時は入力をそのまま返す）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        try:
            d = datetime.strptime(date_str[:8], "%Y%m%d").date()
        except (ValueError, TypeError):
            return str(date_str)
        rel = {-1: "昨日", 0: "今日", 1: "明日", 2: "明後日"}.get((d - today).days)
        base = f"{d:%m/%d} ({self.WEEKDAY_JA[d.weekday()]})"
        return f"{rel} {base}" if rel else base

    # @function name:   _day_label
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _hhmm_rel
    # @function start
    @staticmethod
    def _hhmm_rel(t, ref_date, approx):
        """
        ----------------------------------------------------------------------
        関数概要：時刻を基準日との日差と推定マーク付きで整形する
        - 例: '01:20*+1' / '18:10-1'
        ----------------------------------------------------------------------
        Args:
            - t -> datetime | None --- 対象時刻
            - ref_date -> date | None --- 基準日（日差計算用）
            - approx -> bool --- 推定値かどうか（True なら "*" を付ける）
        ----------------------------------------------------------------------
        Returns:
            - text -> str --- 整形後文字列（None の場合は '--:--'）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        if t is None:
            return "--:--"
        s = f"{t:%H:%M}" + ("*" if approx else "")
        if ref_date:
            diff = (t.date() - ref_date).days
            if diff:
                s += f"{diff:+d}"
        return s

    # @function name:   _hhmm_rel
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _airport_code
    # @function start
    @staticmethod
    def _airport_code(location):
        """
        ----------------------------------------------------------------------
        関数概要：地名文字列から IATA コードと経由フラグを取り出す
        - 例: 'シンシナティ(CVG)(経由)' → ('CVG', True)
        ----------------------------------------------------------------------
        Args:
            - location -> str --- 出発地 / 目的地の表示文字列
        ----------------------------------------------------------------------
        Returns:
            - (code, via) -> tuple[str | None, bool] --- IATA コードと経由かどうか
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        if not isinstance(location, str):
            return None, False
        m = re.search(r'\(([A-Z]{3})\)', location)
        return (m.group(1) if m else None), ('経由' in location)

    # @function name:   _airport_code
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _norm_hhmm
    # @function start
    @classmethod
    def _norm_hhmm(cls, value):
        """
        ----------------------------------------------------------------------
        関数概要：時刻文字列を 'HH:MM' に正規化する
        - 例: '4:05' → '04:05'、None / NaN / '' / '未定' → None
        ----------------------------------------------------------------------
        Args:
            - value -> Any --- 時刻を含む値
        ----------------------------------------------------------------------
        Returns:
            - hhmm -> str | None --- 'HH:MM'（時刻として読めない場合は None）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v4.00 (2026/11/12) - 新規作成
        ----------------------------------------------------------------------
        """
        if not cls._is_str(value):
            return None
        m = re.search(r'(\d{1,2}):(\d{2})', value)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            return None
        return f"{int(m.group(1)):02d}:{m.group(2)}"

    # @function name:   _norm_hhmm
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   flight_state
    # @function start
    @classmethod
    def flight_state(cls, row, flight_type, now=None):
        """
        ----------------------------------------------------------------------
        関数概要：1 便の「いまの状態」を判定する（時刻・状態の解釈はここに一本化）
        - サイトの時刻欄は <strong>最新時刻</strong><span>当初予定</span> の 2 段構成で、
          最新時刻が「実績」か「見込み」かは時刻欄だけでは分からない。状態欄で判定する:
            状態 = 出発 / 到着      → done      （最新時刻 = 実績。最新時刻なしは予定どおり）
            状態 = 遅延             → delayed   （最新時刻 = 見込み。まだ出発/到着していない）
            状態 = 欠航             → cancelled
            状態 = その他の文言     → other     （最新時刻 = 見込み）
            状態なし・最新時刻あり  → estimated （時刻変更。最新時刻 = 見込み）
            状態なし・最新時刻なし  → scheduled （予定どおり）
        - 最新時刻は時刻（HH:MM）しか無いので、予定時刻との前後関係から日付を決める
          （予定 00:05 → 実績 23:51 は前日、予定 22:00 → 見込み 01:30 は翌日）
        ----------------------------------------------------------------------
        Args:
            - row -> pd.Series | dict --- 1 便分のデータ
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
            - now -> datetime | None --- 現在時刻（KST/JST、tz なし）。実績時刻が未来になる日付ずれの補正に使う
        ----------------------------------------------------------------------
        Returns:
            - state -> dict --- phase / sched_txt / latest_txt / status_raw /
                                sched_dt（予定）/ latest_dt（最新）/ time_dt（表示・名古屋側推定に使う時刻。欠航は None）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v4.00 (2026/11/12) - 新規作成（最新時刻を常に「出発済み」扱いしていた不具合を解消）
        ----------------------------------------------------------------------
        """
        is_dep = (flight_type == 'departure')
        prefix = '出発' if is_dep else '到着'
        date_str = str(row.get('取得日', '') or '')

        # 時刻（旧キャッシュは最新時刻を「（実際）」キーで持っているので読み替える）
        sched_txt = cls._norm_hhmm(row.get(f'{prefix}時間（予定）'))
        latest_txt = cls._norm_hhmm(row.get(f'{prefix}時間（最新）')) or cls._norm_hhmm(row.get(f'{prefix}時間（実際）'))
        if latest_txt == sched_txt:
            latest_txt = None

        # 状態欄から段階を判定
        status_raw = row.get(f'{prefix}状態', '')
        status_raw = status_raw.strip() if cls._is_str(status_raw) else ''
        low = status_raw.lower()
        done_words = cls.STATUS_DONE_DEP if is_dep else cls.STATUS_DONE_ARR
        if any(w in low for w in cls.STATUS_CANCELLED):
            phase = 'cancelled'
        elif any(w in low for w in cls.STATUS_DELAYED):
            phase = 'delayed'
        elif any(w in low for w in done_words):
            phase = 'done'
        elif status_raw:
            phase = 'other'
        elif latest_txt:
            phase = 'estimated'
        else:
            phase = 'scheduled'

        # 最新時刻の日付を決める（予定より LATE_MAX_MIN 超の遅れに見える → 実は前日、
        # EARLY_MAX_MIN 超の早発・早着に見える → 実は翌日）
        sched_dt = cls._parse_hhmm(date_str, sched_txt)
        latest_dt = cls._parse_hhmm(date_str, latest_txt)
        if sched_dt and latest_dt:
            diff_min = (latest_dt - sched_dt).total_seconds() / 60
            if diff_min > cls.LATE_MAX_MIN:
                latest_dt -= timedelta(days=1)
            elif diff_min < -cls.EARLY_MAX_MIN:
                latest_dt += timedelta(days=1)
        # 実績なのに未来の時刻になる場合は日付の取り違えなので 1 日戻す
        if phase == 'done' and latest_dt and now and latest_dt > now + timedelta(minutes=10):
            latest_dt -= timedelta(days=1)

        time_dt = None if phase == 'cancelled' else (latest_dt or sched_dt)
        return {
            'phase': phase, 'status_raw': status_raw,
            'sched_txt': sched_txt, 'latest_txt': latest_txt,
            'sched_dt': sched_dt, 'latest_dt': latest_dt, 'time_dt': time_dt,
        }

    # @function name:   flight_state
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   flight_signature
    # @function start
    @classmethod
    def flight_signature(cls, row, flight_type):
        """
        ----------------------------------------------------------------------
        関数概要：変更検出用の比較キー（予定時刻・最新時刻・段階）を返す
        - 前回と今回でこの値が違えば「変更あり」
        - 駐機場・ターミナルの割当は含めない（当日に必ず変わるため通知対象外）
        ----------------------------------------------------------------------
        Args:
            - row -> pd.Series | dict --- 1 便分のデータ（旧形式のキャッシュ行も可）
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
        ----------------------------------------------------------------------
        Returns:
            - signature -> tuple --- (予定時刻, 最新時刻, 段階, その他状態の文言)
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v4.00 (2026/11/12) - 新規作成
        ----------------------------------------------------------------------
        """
        st = cls.flight_state(row, flight_type)
        return (st['sched_txt'], st['latest_txt'], st['phase'], st['status_raw'] if st['phase'] == 'other' else '')

    # @function name:   flight_signature
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _status_line
    # @function start
    def _status_line(self, st, is_dep, with_sched=False):
        """
        ----------------------------------------------------------------------
        関数概要：flight_state の結果を見やすい状態文（1 行）に変換する
        - 🟢 定刻どおり
        - 🟡 時刻変更 → 23:10（予定 22:00、+70分）        ← 見込み（まだ出発/到着していない）
        - 🟠 遅延 → 17:05（予定 11:35、+330分）           ← 見込み（まだ出発/到着していない）
        - ✅ 出発済み 22:40（予定 22:00、+40分）          ← 実績
        - 🔴 欠航 / 🔵 その他（サイトの状態文）
        - 時刻が予定日と別の日になる場合は日付も付ける（例: → 11/14(土) 01:30）
        ----------------------------------------------------------------------
        Args:
            - st -> dict --- flight_state の戻り値
            - is_dep -> bool --- 出発便かどうか
            - with_sched -> bool --- 時刻を含まない状態文にも「（予定 HH:MM）」を付けるか
        ----------------------------------------------------------------------
        Returns:
            - line -> str --- 状態文
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v4.00 (2026/11/12) - 新規作成（_pretty_status を置き換え。見込みと実績を区別）
        ----------------------------------------------------------------------
        """
        tag = "出発" if is_dep else "到着"
        sched_dt, sched_txt = st['sched_dt'], st['sched_txt'] or "--:--"

        # 時刻（予定日と別の日なら日付付き）
        def at(dt):
            if sched_dt and dt.date() != sched_dt.date():
                return f"{self._fmt_md(dt)} {dt:%H:%M}"
            return f"{dt:%H:%M}"

        # 予定との差（'（予定 22:00、+70分）'）
        def versus(dt):
            if sched_dt is None:
                return ""
            d = int(round((dt - sched_dt).total_seconds() / 60))
            return f"（予定 {sched_txt}、定刻）" if d == 0 else f"（予定 {sched_txt}、{d:+d}分）"

        phase, latest_dt = st['phase'], st['latest_dt']
        sched_note = f"（予定 {sched_txt}）" if with_sched and st['sched_txt'] else ""
        if phase == 'cancelled':
            return "🔴 欠航" + sched_note
        if phase == 'done':
            t = st['time_dt']
            return f"✅ {tag}済み {at(t)}{versus(t)}" if t else f"✅ {tag}済み"
        if phase == 'delayed':
            return f"🟠 遅延 → {at(latest_dt)}{versus(latest_dt)}" if latest_dt else "🟠 遅延" + sched_note
        if phase == 'estimated' and latest_dt:
            return f"🟡 時刻変更 → {at(latest_dt)}{versus(latest_dt)}"
        if phase == 'other':
            return f"🔵 {st['status_raw']}" + (f" → {at(latest_dt)}{versus(latest_dt)}" if latest_dt else sched_note)
        return "🟢 定刻どおり" + sched_note

    # @function name:   _status_line
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _format_row
    # @function start
    def _format_row(self, row, flight_type, today, now=None, change=None):
        """
        ----------------------------------------------------------------------
        関数概要：1 便を Discord 埋め込みフィールド 1 枠に整形する
        - name : 🛫 K4 219 ｜ 今日 11/08 (日)
        - value: ICN → NGO → CVG
                 `🛫 ICN 11/08(日) 22:40 KST (実績)`
                 `🛬 NGO 11/09(月) 00:35 JST (推定)`
                 `ICN Cargo(N) ・ 駐機場 675`
                 ✅ 出発済み 22:40（予定 22:00、+40分）
        - ICN 側の時刻は「実績 > 見込み > 予定」の順で分かっている最新のものを表示し、
          実績は (実績)、見込みは (見込み) を付ける（予定どおりの場合は何も付けない）
        - 名古屋側の時刻は ICN 側の表示時刻 ± 標準所要時間（推定）
        - change を渡すと、変更内容（前回の状態など）を状態文の下に添える
        ----------------------------------------------------------------------
        Args:
            - row -> pd.Series | dict --- 1 便分のデータ行（削除通知では前回のデータ行）
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
            - today -> date --- 基準日（相対日付ラベル用）
            - now -> datetime | None --- 現在時刻（tz なし。flight_state の日付補正用）
            - change -> dict | None --- 変更情報 {'kind': 'new' | 'changed' | 'moved' | 'removed', 'prev': 前回のデータ行}
        ----------------------------------------------------------------------
        Returns:
            - field -> dict --- 埋め込みフィールド（name / value / inline）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
            - revision       v3.02 (2026/11/09) - ターミナル・駐機場の行を追加
            - revision       v3.03 (2026/11/11) - 予定時刻が欠損している行でも前回値の比較で例外にならないよう修正
            - revision       v4.00 (2026/11/12) - 時刻・状態の判定を flight_state に一本化（実績 / 見込みを区別、日またぎ対応）
                                                  変更情報を '変更種別' 列ではなく change 引数で受け取る
        ----------------------------------------------------------------------
        """
        is_dep = (flight_type == 'departure')
        date_str = str(row.get('取得日', '') or '')
        loc_key = '目的地' if is_dep else '出発地'
        st = self.flight_state(row, flight_type, now)
        kind = (change or {}).get('kind', '')
        prev_row = (change or {}).get('prev')

        # ICN 側の時刻（実績 > 見込み > 予定）。欠航は予定時刻を表示
        icn_dt = st['time_dt'] or st['sched_dt']
        if st['phase'] == 'done':
            mark = " (実績)"
        elif st['latest_dt'] and st['phase'] != 'cancelled':
            mark = " (見込み)"
        else:
            mark = ""
        icn_line = f"ICN {self._fmt_md(icn_dt)} {icn_dt:%H:%M} KST{mark}" if icn_dt else "ICN --/-- --:-- KST"

        # 名古屋側の時刻（ICN 側の表示時刻 ± 標準所要時間）
        if st['time_dt'] is None:
            ngo_line = "NGO --/-- --:-- JST"
        else:
            ngo_dt = st['time_dt'] + timedelta(minutes=self.FLIGHT_MIN_ICN_NGO) if is_dep \
                else st['time_dt'] - timedelta(minutes=self.FLIGHT_MIN_NGO_ICN)
            ngo_line = f"NGO {self._fmt_md(ngo_dt)} {ngo_dt:%H:%M} JST (推定)"
        times = [f"`🛫 {icn_line}`", f"`🛬 {ngo_line}`"] if is_dep else [f"`🛫 {ngo_line}`", f"`🛬 {icn_line}`"]

        # 経路
        code, via = self._airport_code(row.get(loc_key, ''))
        if is_dep:
            route = "ICN → NGO" + (f" → {code}" if code and code != 'NGO' else "")
        else:
            route = (f"{code} → " if code and code != 'NGO' else "") + "NGO → ICN"

        # v3.02: ICN 側のターミナル・駐機場（駐機場は未割当なら '--'）
        terminal = row.get('ターミナル', '')
        stand = row.get('駐機場', '')
        spot_parts = []
        if self._is_str(terminal):
            spot_parts.append(terminal.strip())
        spot_parts.append(f"駐機場 {stand.strip() if self._is_str(stand) else '--'}")
        spot_line = "`ICN " + " ・ ".join(spot_parts) + "`"

        # 状態文 + 変更内容
        status_lines = [self._status_line(st, is_dep)]
        if kind == 'new':
            status_lines.append("🆕 新しく追加された便")
        elif kind == 'removed':
            status_lines.append("🗑️ スケジュールから削除された便")
        elif kind in ('changed', 'moved') and prev_row is not None:
            pst = self.flight_state(prev_row, flight_type, now)
            if kind == 'moved':
                prev_line = f"🔔 日付変更 ・ 前回: {self._fmt_md(pst['sched_dt'])} {pst['sched_txt'] or '--:--'}"
                if pst['phase'] != 'scheduled':
                    prev_line += " ・ " + self._status_line(pst, is_dep)
                status_lines.append(prev_line)
            else:
                status_lines.append("🔔 前回: " + self._status_line(pst, is_dep, with_sched=(pst['sched_txt'] != st['sched_txt'])))

        # 1 便 = 埋め込みフィールド 1 枠
        badge = {'new': "🆕 ", 'changed': "🔔 ", 'moved': "🔔 ", 'removed': "🗑️ "}.get(kind, "")
        icon = "🛫" if is_dep else "🛬"
        fcode = self._flight_code(row.get('便名', ''))
        name = f"{badge}{icon} {fcode} ｜ {self._day_label(date_str, today)}"
        value = "\n".join([route, *times, spot_line, *status_lines])
        return {"name": name[:256], "value": value[:1024], "inline": False}

    # @function name:   _format_row
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _fmt_md
    # @function start
    def _fmt_md(self, d):
        """
        ----------------------------------------------------------------------
        関数概要：日付を '11/09(月)' 形式に整形する
        ----------------------------------------------------------------------
        Args:
            - d -> datetime | date | None --- 対象日付
        ----------------------------------------------------------------------
        Returns:
            - text -> str --- 整形後文字列（None の場合は '--/--'）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        return "--/--" if d is None else f"{d:%m/%d}({self.WEEKDAY_JA[d.weekday()]})"

    # @function name:   _fmt_md
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _ngo_time_suffix
    # @function start
    @staticmethod
    def _ngo_time_suffix(txt):
        """
        ----------------------------------------------------------------------
        関数概要：名古屋側時刻文字列の日差・推定マークを日本語の補足に変換する
        - 例: '05:40*+1' → ' (翌日・推定)'
        ----------------------------------------------------------------------
        Args:
            - txt -> str --- _hhmm_rel で整形した時刻文字列
        ----------------------------------------------------------------------
        Returns:
            - suffix -> str --- 補足文字列（補足なしの場合は空文字）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ----------------------------------------------------------------------
        """
        parts = []
        if "+1" in txt:
            parts.append("翌日")
        elif "-1" in txt:
            parts.append("前日")
        if "*" in txt:
            parts.append("推定")
        return f" ({'・'.join(parts)})" if parts else ""

    # @function name:   _ngo_time_suffix
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _build_fields
    # @function start
    def _build_fields(self, df, flight_type, today, now=None):
        """
        ----------------------------------------------------------------------
        関数概要：便ごとの埋め込みフィールド一覧を組み立てる（日付・予定時刻順）
        - 便と便の間に 1 行空ける（Changi 通知と同じ）
        ----------------------------------------------------------------------
        Args:
            - df -> pd.DataFrame | None --- 便データ（None・空は 0 件扱い）
            - flight_type -> str --- フライトタイプ ('departure' or 'arrival')
            - today -> date --- 基準日
            - now -> datetime | None --- 現在時刻（tz なし。flight_state の日付補正用）
        ----------------------------------------------------------------------
        Returns:
            - fields -> list[dict] --- 埋め込みフィールド一覧
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
            - revision       v3.03 (2026/11/11) - 便間の空行を追加・空データに対応（Changi 通知に準拠）
            - revision       v4.00 (2026/11/12) - now 引数を追加
        ----------------------------------------------------------------------
        """
        if df is None or len(df) == 0:
            return []
        sched_key = '出発時間（予定）' if flight_type == 'departure' else '到着時間（予定）'
        fields = []
        if '取得日' in df.columns:
            df = df.sort_values(['取得日', sched_key], kind='stable') if sched_key in df.columns else df.sort_values('取得日')
        for _, row in df.iterrows():
            fields.append(self._format_row(row, flight_type, today, now))
        # 便と便の間に 1 行空ける（最後の便には付けない）
        for fld in fields[:-1]:
            fld["value"] += "\n\u200b"
        return fields

    # @function name:   _build_fields
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _fields_to_text
    # @function start
    @staticmethod
    def _fields_to_text(fields):
        """
        ----------------------------------------------------------------------
        関数概要：埋め込みフィールド一覧を標準出力用のテキストに変換する
        ----------------------------------------------------------------------
        Args:
            - fields -> list[dict] --- 埋め込みフィールド一覧
        ----------------------------------------------------------------------
        Returns:
            - text -> str --- 表示用テキスト（0 件の場合は '  該当便なし'）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
            - revision       v3.03 (2026/11/11) - 便間の空行（ゼロ幅スペース）を除いて表示
        ----------------------------------------------------------------------
        """
        if not fields:
            return "  該当便なし"
        return "\n".join(f"  {f['name']}\n" + "\n".join("    " + l for l in f["value"].replace("\u200b", "").splitlines()) for f in fields)

    # @function name:   _fields_to_text
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _embeds
    # @function start
    @staticmethod
    def _embeds(title, fields, color):
        """
        ----------------------------------------------------------------------
        関数概要：フィールド一覧を Discord 埋め込みに分割して組み立てる
        - 1 埋め込みあたり 25 フィールド上限のため 24 件ずつ分割
        ----------------------------------------------------------------------
        Args:
            - title -> str --- 埋め込みタイトル
            - fields -> list[dict] --- 埋め込みフィールド一覧
            - color -> int --- 埋め込みの色
        ----------------------------------------------------------------------
        Returns:
            - embeds -> list[dict] --- 埋め込みリスト（0 件の場合は '該当便なし' の 1 件）
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.03 (2026/11/11) - 新規作成（Changi 通知に準拠）
        ----------------------------------------------------------------------
        """
        if not fields:
            return [{"title": title, "description": "該当便なし", "color": color}]
        return [{"title": title if i == 0 else f"{title} (続き)", "color": color, "fields": fields[i:i + 24]}
                for i in range(0, len(fields), 24)]  # 25 fields/embed 上限

    # @function name:   _embeds
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _post_webhook
    # @function start
    def _post_webhook(self, payload, label=""):
        """
        ----------------------------------------------------------------------
        関数概要：Discord Webhook に 1 メッセージ送信する（レート制限時は待って再送）
        ----------------------------------------------------------------------
        Args:
            - payload -> dict --- 送信内容（content / embeds）
            - label -> str --- ログ表示用のラベル
        ----------------------------------------------------------------------
        Returns:
            - success -> bool --- 送信成功時 True
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v4.00 (2026/11/12) - 新規作成（一覧通知・個別通知で共用）
        ----------------------------------------------------------------------
        """
        try:
            response = None
            for _ in range(3):
                response = requests.post(
                    self.discord_webhook_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                if response.status_code != 429:
                    break
                # レート制限: 指定秒数（最大 10 秒）待って再送
                try:
                    wait = float(response.headers.get('Retry-After', '2'))
                except ValueError:
                    wait = 2.0
                time.sleep(min(max(wait, 0.5), 10.0))
            if response.status_code in (200, 204):
                print(f"✓ Discord通知送信成功{label}")
                return True
            print(f"✗ エラー: Discord通知送信失敗{label}")
            print(f"  ステータスコード: {response.status_code}")
            print(f"  レスポンス: {response.text}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"✗ エラー: Discord通知送信中に通信エラー{label} - {e}")
            return False

    # @function name:   _post_webhook
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   send_discord_notification
    # @function start
    def send_discord_notification(self, df_departure, df_arrival, start_date, end_date, airport='NGO'):
        """
        ----------------------------------------------------------------------
        関数概要：Discordに一覧通知を送信（Changi 通知と同一フォーマット）
        - 出発便（青）・到着便（緑）の埋め込みを 1 メッセージにまとめて送信
        - 1 便 = 埋め込みフィールド 1 枠
        - 見出し: ICN ⇄ NGO カーゴ便  |  出発 N 件 / 到着 M 件
        - 名古屋側の時刻は標準所要時間からの推定
        - 24 フィールドごとに埋め込みを分割、10 embeds/message で送信
        - 変更があった便の個別通知は send_change_notifications を使う
        ----------------------------------------------------------------------
        Args:
            - df_departure -> pd.DataFrame | None --- 出発便データ（None・空は「該当便なし」）
            - df_arrival -> pd.DataFrame | None --- 到着便データ（None・空は「該当便なし」）
            - start_date -> str --- 開始日 (YYYYMMDD)
            - end_date -> str --- 終了日 (YYYYMMDD)
            - airport -> str --- 空港コード (デフォルト: NGO)
        ----------------------------------------------------------------------
        Returns:
            - success -> bool --- 全バッチ送信成功時True
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
            - revision       v3.03 (2026/11/11) - 出発便・到着便を 1 メッセージに統合し Changi 通知に完全準拠
                                                  （引数を df, flight_type → df_departure, df_arrival に変更）
            - revision       v4.00 (2026/11/12) - 変化件数・🔔 表示を廃止（変更は個別通知に移行）
        ----------------------------------------------------------------------
        """
        if not self.discord_webhook_url:
            print("エラー: Discord Webhook URLが設定されていません")
            print("環境変数 DISCORD_WEBHOOK_URL を設定するか、初期化時に指定してください")
            return False

        n_dep = 0 if df_departure is None else len(df_departure)
        n_arr = 0 if df_arrival is None else len(df_arrival)
        if n_dep == 0 and n_arr == 0:
            print("送信するデータがありません")
            return False

        try:
            now = datetime.now(self.JST)
            today = now.date()
            now_naive = now.replace(tzinfo=None)
            dep_fields = self._build_fields(df_departure, 'departure', today, now_naive)
            arr_fields = self._build_fields(df_arrival, 'arrival', today, now_naive)
            period = f"{self._day_label(start_date, today)} 〜 {self._day_label(end_date, today)}"
            title = f"ICN ⇄ {airport} カーゴ便  |  出発 {n_dep} 件 / 到着 {n_arr} 件"

            # 標準出力表示
            print(title)
            print(f"対象期間: {period}")
            print(f"[出発便  ICN → {airport}]")
            print(self._fields_to_text(dep_fields))
            print(f"[到着便  {airport} → ICN]")
            print(self._fields_to_text(arr_fields))

            # 埋め込み組み立て（出発 = 青 / 到着 = 緑、フッターは最後の埋め込みに付ける）
            embeds = self._embeds(f"出発便  ICN → {airport}  ({n_dep} 件)", dep_fields, self._color('DISCORD_COLOR_DEP', 0x3B82F6)) + \
                     self._embeds(f"到着便  {airport} → ICN  ({n_arr} 件)", arr_fields, self._color('DISCORD_COLOR_ARR', 0x22C55E))
            embeds[-1]["footer"] = {
                "text": f"KST=韓国時間 / JST=日本時間 ・ 日付は各空港の現地日付 ・ 実績=出発/到着済みの時刻 ・ 見込み=変更後の予定時刻 ・ 推定=標準所要時間からの概算 ・ 更新 {now:%m/%d %H:%M} JST"
            }
            content = f"**{title}**\n対象期間: {period}"

            MAX_EMBEDS_PER_MSG = 10
            print(f"  Webhook URL: {self.discord_webhook_url[:50]}...")
            print(f"  送信embed数: {len(embeds)}")
            success = True
            for batch_start in range(0, len(embeds), MAX_EMBEDS_PER_MSG):
                batch = embeds[batch_start:batch_start + MAX_EMBEDS_PER_MSG]
                payload = {"embeds": batch}
                if batch_start == 0:
                    payload["content"] = content
                batch_num = batch_start // MAX_EMBEDS_PER_MSG + 1
                if not self._post_webhook(payload, f"（バッチ {batch_num}）"):
                    success = False
                if batch_start + MAX_EMBEDS_PER_MSG < len(embeds):
                    time.sleep(0.5)
            return success

        except Exception as e:
            print(f"✗ エラー: Discord通知送信中に例外が発生")
            print(f"  例外内容: {e}")
            print(f"  例外タイプ: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            return False

    # @function name:   send_discord_notification
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   _change_headline
    # @function start
    def _change_headline(self, change, airport, now=None):
        """
        ----------------------------------------------------------------------
        関数概要：個別通知の本文（スマホの通知にも出る 2 行の要約）を作る
        - 1 行目: **K4 217 ｜ ICN → NGO ｜ 11/13(金)**
        - 2 行目: 変更内容（例: 🟠 遅延 → 17:05（予定 11:35、+330分））
        ----------------------------------------------------------------------
        Args:
            - change -> dict --- 変更情報（flight_type / kind / row / prev）
            - airport -> str --- 空港コード
            - now -> datetime | None --- 現在時刻（tz なし）
        ----------------------------------------------------------------------
        Returns:
            - content -> str --- メッセージ本文
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v4.00 (2026/11/12) - 新規作成
        ----------------------------------------------------------------------
        """
        flight_type, kind, row = change['flight_type'], change['kind'], change['row']
        is_dep = (flight_type == 'departure')
        st = self.flight_state(row, flight_type, now)
        day = self._fmt_md(st['sched_dt']) if st['sched_dt'] else str(row.get('取得日', '') or '')
        sched = st['sched_txt'] or "--:--"
        route = f"ICN → {airport}" if is_dep else f"{airport} → ICN"
        if kind == 'new':
            summary = f"🆕 新しく追加された便（予定 {sched}）"
        elif kind == 'removed':
            summary = f"🗑️ スケジュールから削除された便（予定 {sched}）"
        elif kind == 'moved' and change.get('prev') is not None:
            pst = self.flight_state(change['prev'], flight_type, now)
            summary = f"🔔 日付変更: {self._fmt_md(pst['sched_dt'])} {pst['sched_txt'] or '--:--'} → {day} {sched}"
            if st['phase'] != 'scheduled':
                summary += " ・ " + self._status_line(st, is_dep)
        else:
            summary = self._status_line(st, is_dep, with_sched=True)
        return f"**{self._flight_code(row.get('便名', ''))} ｜ {route} ｜ {day}**\n{summary}"

    # @function name:   _change_headline
    # @function end
    # ======================================================================================#

    # ======================================================================================#
    # @function name:   send_change_notifications
    # @function start
    def send_change_notifications(self, changes, airport='NGO'):
        """
        ----------------------------------------------------------------------
        関数概要：変更があった便を 1 便 = 1 メッセージで Discord に個別通知する
        - 本文: 便名・経路・日付と変更内容の要約（スマホの通知で内容が分かる）
        - 埋め込み: 一覧通知と同じ 1 便分の枠（出発 = 青 / 到着 = 緑）+ 前回の状態
        ----------------------------------------------------------------------
        Args:
            - changes -> list[dict] --- 変更情報のリスト。各要素は
                  flight_type -> str  --- 'departure' or 'arrival'
                  kind        -> str  --- 'new'（追加）/ 'changed'（時刻・状態の変更）/
                                          'moved'（日付変更）/ 'removed'（削除）
                  row         -> dict --- 今回のデータ行（removed は前回のデータ行）
                  prev        -> dict | None --- 前回のデータ行（changed / moved）
            - airport -> str --- 空港コード (デフォルト: NGO)
        ----------------------------------------------------------------------
        Returns:
            - results -> list[bool] --- changes と同じ並びの送信結果
        ----------------------------------------------------------------------
        Notes:
            - author         Kidera-Shunsuke
            - revision       v4.00 (2026/11/12) - 新規作成（変更があった便の個別通知）
        ----------------------------------------------------------------------
        """
        if not self.discord_webhook_url:
            print("エラー: Discord Webhook URLが設定されていません")
            return [False] * len(changes)

        now = datetime.now(self.JST)
        today = now.date()
        now_naive = now.replace(tzinfo=None)
        footer = f"KST=韓国時間 / JST=日本時間 ・ 実績=出発/到着済み ・ 見込み=変更後の予定 ・ 推定=標準所要時間からの概算 ・ 更新 {now:%m/%d %H:%M} JST"
        results = []
        for i, change in enumerate(changes):
            try:
                flight_type = change['flight_type']
                is_dep = (flight_type == 'departure')
                field = self._format_row(change['row'], flight_type, today, now_naive, change=change)
                content = self._change_headline(change, airport, now_naive)
                color = self._color('DISCORD_COLOR_DEP', 0x3B82F6) if is_dep else self._color('DISCORD_COLOR_ARR', 0x22C55E)
                embed = {"title": field["name"], "description": field["value"], "color": color, "footer": {"text": footer}}

                # 標準出力表示
                print(content.replace("**", ""))
                print(self._fields_to_text([field]))
                results.append(self._post_webhook({"content": content, "embeds": [embed]}, f"（個別 {i + 1}/{len(changes)}）"))
            except Exception as e:  # noqa: BLE001
                print(f"✗ エラー: 個別通知の作成中に例外が発生 - {type(e).__name__}: {e}")
                results.append(False)
            if i + 1 < len(changes):
                time.sleep(0.6)  # Webhook のレート制限（5 件 / 2 秒）を避ける
        return results

    # @function name:   send_change_notifications
    # @function end
    # ======================================================================================#


# ======================================================================================#
# メイン処理（動作確認用）
# ======================================================================================#

# ======================================================================================#
# @function name:   main
# @function start
def main():
    """
    ----------------------------------------------------------------------
    関数概要：メイン関数
    - スクレイピングのテスト・使用例を実行
    - 動作確認用
    ----------------------------------------------------------------------
    Args:
        - なし
    ----------------------------------------------------------------------
    Returns:
        - なし
    ----------------------------------------------------------------------
    Notes:
        - author         Kidera-Shunsuke
        - revision       v1.01 (2025/11/01) - 到着便対応追加
    ----------------------------------------------------------------------
    """
    print("=" * 60)
    print("仁川国際空港 貨物出発時刻表スクレイピングプログラム")
    print("=" * 60)
    
    scraper = IncheonCargoScraper()
    
    # 使用例1: 今日のデータを取得（デバッグモード）
    #print("\n[例1] 今日のデータを取得")
    #df = scraper.scrape(output_format='csv', save_html=True)
    print("\n[例3] 複数日のデータを取得")
    df = scraper.scrape_multiple_dates('20251101', '20251108', airport='NGO', output_format='excel')
    
    if df is not None and len(df) > 0:
        print("\n取得したデータのプレビュー:")
        print(df.head())
        print(f"\n列名: {list(df.columns)}")
    else:
        print("\nデータが取得できませんでした。")
        print("debug_html_*.html ファイルを確認して、ページ構造を調査してください。")
    
    # 使用例2: 特定の日付のデータを取得
    # print("\n[例2] 特定の日付のデータを取得")
    # df = scraper.scrape(date_str='20241129', airport='NGO', output_format='json', save_html=True)
    
    # 使用例3: 複数日のデータを取得

    print("\n" + "=" * 60)
    print("処理が完了しました")
    print("=" * 60)


# @function name:   main
# @function end
# ======================================================================================#


if __name__ == '__main__':
    # 独立実行時の処理
    main()
