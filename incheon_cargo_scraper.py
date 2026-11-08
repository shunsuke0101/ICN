# coding: utf_8
# -----------------------------------------------------------------------------------#
# @file           incheon_cargo_scraper.py
# @brief          仁川国際空港 貨物出発・到着スケジュール スクレイピングシステム
# @author         GitHub Copilot
# @date           2025/11/01
# $Version:       1.01
# $Revision:      2025/11/01 - 到着便対応追加
# @note           仁川国際空港の貨物出発・到着スケジュールをWebスクレイピング
#                 Discord Webhook通知機能を含む
# @attention      出発便APIエンドポイント: https://www.airport.kr/depCargo/ap_ja/depCargoSchList.do
#                 到着便APIエンドポイント: https://www.airport.kr/arrCargo/ap_ja/arrCargoSchList.do
#                 データ構造: div.data > div.body > div.group > div.row
# @par            History
#                 v1.00 (2025/11/01) - 初期実装・Discord通知機能追加
#                 v1.01 (2025/11/01) - 到着便データ取得機能追加・CSV出力デフォルト無効化
# Copyright (c) 2025. All Rights reserved.
#
# -----------------------------------------------------------------------------------#

import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import re
import os
from dotenv import load_dotenv

# .envファイルを読み込む
load_dotenv()


# ======================================================================================#
# @class name:   IncheonCargoScraper
class IncheonCargoScraper:
    """
    ---------------------------------------------------------------------
    クラス概要： 仁川国際空港の貨物スケジュールをスクレイピングするクラス
    
    主な機能:
    - 貨物出発・到着スケジュールの取得
    - 複数日のデータ取得
    - CSV/JSON/Excel形式でのエクスポート
    - Discord Webhook通知
    ----------------------------------------------------------------------
    """
    
    # ======================================================================================#
    # @method name:   __init__
    def __init__(self, discord_webhook_url=None):
        """
        ---------------------------------------------------------------------
        メソッド概要：  コンストラクタ
        - APIエンドポイントとヘッダーを設定
        - Discord Webhook URLを初期化
        ----------------------------------------------------------------------
        Args:
            discord_webhook_url (str, optional): Discord Webhook URL
        ---------------------------------------------------------------------
        Returns:
            なし
        ---------------------------------------------------------------------
        Notes:
            - author         GitHub Copilot
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ---------------------------------------------------------------------
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
    
    # ======================================================================================#
    # @method name:   build_params
    def build_params(self, date_str=None, airport='NGO', start_time='0000', end_time='2359', flight_type='departure'):
        """
        ---------------------------------------------------------------------
        メソッド概要：  APIリクエストのパラメータを構築
        - 日付、空港、時刻範囲を指定してパラメータ辞書を生成
        ----------------------------------------------------------------------
        Args:
            date_str (str, optional): 日付 (YYYYMMDD形式)。Noneの場合は今日
            airport (str): 空港コード (デフォルト: NGO - 名古屋)
            start_time (str): 開始時刻 (HHMM形式)
            end_time (str): 終了時刻 (HHMM形式)
            flight_type (str): フライトタイプ ('departure' or 'arrival')
        ---------------------------------------------------------------------
        Returns:
            dict: APIリクエストパラメータ
        ---------------------------------------------------------------------
        Notes:
            - author         GitHub Copilot
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ---------------------------------------------------------------------
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
    
    # ======================================================================================#
    # @method name:   fetch_page
    def fetch_page(self, params, flight_type='departure'):
        """
        ---------------------------------------------------------------------
        メソッド概要：  ページを取得する（APIエンドポイント使用）
        - APIエンドポイントにリクエストを送信
        - レスポンスをBeautifulSoupでパース
        ----------------------------------------------------------------------
        Args:
            params (dict): リクエストパラメータ
            flight_type (str): フライトタイプ ('departure' or 'arrival')
        ---------------------------------------------------------------------
        Returns:
            BeautifulSoup: パースされたHTML
        ---------------------------------------------------------------------
        Notes:
            - author         GitHub Copilot
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ---------------------------------------------------------------------
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
    
    # ======================================================================================#
    # @method name:   parse_cargo_table
    def parse_cargo_table(self, soup, flight_type='departure'):
        """
        ---------------------------------------------------------------------
        メソッド概要：  貨物スケジュールテーブルをパース
        - HTMLからdiv.data構造を解析
        - フライト情報を抽出してリスト化
        ----------------------------------------------------------------------
        Args:
            soup (BeautifulSoup): パースされたHTML
            flight_type (str): フライトタイプ ('departure' or 'arrival')
        ---------------------------------------------------------------------
        Returns:
            list: 貨物情報のリスト（辞書形式）
        ---------------------------------------------------------------------
        Notes:
            - author         GitHub Copilot
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ---------------------------------------------------------------------
        """
        cargo_data = []
        
        print("  HTML解析中...")
        
        # 出発便か到着便かでキー名を設定
        time_key_scheduled = '出発時間（予定）' if flight_type == 'departure' else '到着時間（予定）'
        time_key_actual = '出発時間（実際）' if flight_type == 'departure' else '到着時間（実際）'
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
                            # 予定時間を取得（strong要素内）
                            time_elem = col1.find('strong')
                            original_scheduled = None
                            if time_elem:
                                original_scheduled = time_elem.get_text(strip=True)
                            
                            # 実際の時間を取得（span要素内）
                            # time divの中のspanを探す
                            actual_time = None
                            time_div = col1.find('div', class_='time')
                            if time_div:
                                # span要素を直接探す
                                time_span = time_div.find('span')
                                if time_span:
                                    actual_time = time_span.get_text(strip=True)
                            
                            # 実際の時間が存在する場合、時間を入れ替える
                            # 予定 ← 実際の時間、実際 ← もともとの予定時間
                            if actual_time:
                                row_data[time_key_scheduled] = actual_time
                                row_data[time_key_actual] = original_scheduled
                            else:
                                # 実際の時間がない場合は予定時間のみ
                                row_data[time_key_scheduled] = original_scheduled
                        
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
                        
                        # 駐機場
                        col5 = toggle_row.find('div', class_='col5')
                        if col5:
                            # hidden-textを除外
                            for hidden in col5.find_all('i', class_='hidden-text'):
                                hidden.decompose()
                            gate = col5.get_text(strip=True)
                            if gate:
                                row_data['駐機場'] = gate
                        
                        # 状態（出発または到着）
                        col6 = toggle_row.find('div', class_='col6')
                        if col6:
                            # hidden-textを除外
                            for hidden in col6.find_all('i', class_='hidden-text'):
                                hidden.decompose()
                            status = col6.get_text(strip=True)
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
    
    # ======================================================================================#
    # @method name:   scrape
    def scrape(self, date_str=None, airport='NGO', output_format=None, save_html=False, flight_type='departure'):
        """
        ---------------------------------------------------------------------
        メソッド概要：  貨物スケジュールをスクレイピング
        - 指定日付・空港のデータを取得
        - オプションでファイル保存
        ----------------------------------------------------------------------
        Args:
            date_str (str, optional): 日付 (YYYYMMDD形式)。Noneの場合は今日
            airport (str): 空港コード (デフォルト: NGO)
            output_format (str): 出力形式 ('csv', 'json', 'excel')
            save_html (bool): HTMLを保存するかどうか
            flight_type (str): フライトタイプ ('departure' or 'arrival')
        ---------------------------------------------------------------------
        Returns:
            pd.DataFrame: スクレイピングされたデータ
        ---------------------------------------------------------------------
        Notes:
            - author         GitHub Copilot
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ---------------------------------------------------------------------
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
            print("警告: データが見つかりませんでした")
            print("  ヒント: 日付やパラメータを確認してください")
            print("  save_html=True を設定してHTMLを確認することができます")
            return pd.DataFrame()
        
        # DataFrameに変換
        df = pd.DataFrame(cargo_data)
        
        # 必須の列が存在することを保証（実際の時間が存在しない場合でも列を作成）
        time_key_scheduled = '出発時間（予定）' if flight_type == 'departure' else '到着時間（予定）'
        time_key_actual = '出発時間（実際）' if flight_type == 'departure' else '到着時間（実際）'
        
        if time_key_actual not in df.columns:
            df[time_key_actual] = None
        
        print(f"\n✓ 取得したデータ: {len(df)} 件")
        
        # データを保存
        if output_format and len(df) > 0:
            self.save_data(df, date_str, airport, output_format)
        
        return df
    
    # ======================================================================================#
    # @method name:   save_data
    def save_data(self, df, date_str, airport, output_format):
        """
        ---------------------------------------------------------------------
        メソッド概要：  データを保存する
        - CSV/JSON/Excel形式でエクスポート
        - logディレクトリに保存
        ----------------------------------------------------------------------
        Args:
            df (pd.DataFrame): 保存するデータ
            date_str (str): 日付
            airport (str): 空港コード
            output_format (str): 出力形式 ('csv', 'json', 'excel')
        ---------------------------------------------------------------------
        Returns:
            なし
        ---------------------------------------------------------------------
        Notes:
            - author         GitHub Copilot
            - revision       v1.00 (2025/11/01) - 初期実装
        ---------------------------------------------------------------------
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
    
    # ======================================================================================#
    # @method name:   scrape_multiple_dates
    def scrape_multiple_dates(self, start_date, end_date, airport='NGO', output_format=None, flight_type='departure'):
        """
        ---------------------------------------------------------------------
        メソッド概要：  複数日のデータをスクレイピング
        - 指定期間のデータを日ごとに取得
        - 結果を結合して返す
        ----------------------------------------------------------------------
        Args:
            start_date (str): 開始日 (YYYYMMDD形式)
            end_date (str): 終了日 (YYYYMMDD形式)
            airport (str): 空港コード (デフォルト: NGO)
            output_format (str): 出力形式 ('csv', 'json', 'excel')
            flight_type (str): フライトタイプ ('departure' or 'arrival')
        ---------------------------------------------------------------------
        Returns:
            pd.DataFrame: 結合されたデータ
        ---------------------------------------------------------------------
        Notes:
            - author         GitHub Copilot
            - revision       v1.01 (2025/11/01) - 到着便対応追加
        ---------------------------------------------------------------------
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
    
    # ======================================================================================#
    # @method name:   send_discord_notification
    # ── 表示フォーマット（Changi 通知と共通の表形式） ─────────────────────────
    # 名古屋側時刻の推定に使う標準所要時間（分）。.env の FLIGHT_MINUTES_ICN_NGO / NGO_ICN で変更可
    FLIGHT_MIN_ICN_NGO = int(os.getenv('FLIGHT_MINUTES_ICN_NGO', '115'))
    FLIGHT_MIN_NGO_ICN = int(os.getenv('FLIGHT_MINUTES_NGO_ICN', '125'))
    WEEKDAY_JA = "月火水木金土日"

    @staticmethod
    def _color(env_name, default):
        v = (os.getenv(env_name) or '').strip().lstrip('#')
        try:
            return int(v, 16) if v else default
        except ValueError:
            return default

    @staticmethod
    def _is_str(v):
        return isinstance(v, str) and v.strip() not in ('', 'N/A', 'nan', 'None', '未定')

    @staticmethod
    def _flight_code(fn):
        """'K4219' → 'K4 219'、'JL6749' → 'JL 6749'"""
        fn = (fn or '?').strip().replace(' ', '')
        m = re.match(r'^([A-Z][A-Z0-9]|[0-9][A-Z])(\d{1,5}[A-Z]?)$', fn.upper())
        return f"{m.group(1)} {m.group(2)}" if m else fn

    @staticmethod
    def _parse_hhmm(date_str, hhmm):
        """'20261108' + '22:00' → datetime（韓国・日本は同じ UTC+9 なので時差換算不要）"""
        if not date_str or not IncheonCargoScraper._is_str(hhmm):
            return None
        m = re.search(r'(\d{1,2}):(\d{2})', hhmm)
        if not m:
            return None
        try:
            return datetime.strptime(f"{date_str[:8]} {int(m.group(1)):02d}:{m.group(2)}", "%Y%m%d %H:%M")
        except ValueError:
            return None

    def _day_label(self, date_str, today):
        try:
            d = datetime.strptime(date_str[:8], "%Y%m%d").date()
        except (ValueError, TypeError):
            return str(date_str)
        rel = {-1: "昨日", 0: "今日", 1: "明日", 2: "明後日"}.get((d - today).days)
        base = f"{d:%m/%d} ({self.WEEKDAY_JA[d.weekday()]})"
        return f"{rel} {base}" if rel else base

    @staticmethod
    def _hhmm_rel(t, ref_date, approx):
        """'01:20*+1' のように推定マークと日差を付ける"""
        if t is None:
            return "--:--"
        s = f"{t:%H:%M}" + ("*" if approx else "")
        if ref_date:
            diff = (t.date() - ref_date).days
            if diff:
                s += f"{diff:+d}"
        return s

    @staticmethod
    def _airport_code(location):
        """'シンシナティ(CVG)(経由)' → ('CVG', True)"""
        if not isinstance(location, str):
            return None, False
        m = re.search(r'\(([A-Z]{3})\)', location)
        return (m.group(1) if m else None), ('経由' in location)

    def _format_row(self, row, flight_type, today):
        """1 便 1 行（等幅前提）
        出発: 'ICN 22:00    K4 219   NGO 23:55*   定刻 (→CVG)'
        到着: 'NGO 02:10*   JL 6749  ICN 04:15    定刻'
        """
        is_dep = (flight_type == 'departure')
        date_str = str(row.get('取得日', '') or '')
        sched_key = '出発時間（予定）' if is_dep else '到着時間（予定）'
        actual_key = '出発時間（実際）' if is_dep else '到着時間（実際）'
        status_key = '出発状態' if is_dep else '到着状態'
        loc_key = '目的地' if is_dep else '出発地'

        sched_raw = row.get(sched_key, '')
        actual_raw = row.get(actual_key, '')
        sched_dt = self._parse_hhmm(date_str, sched_raw)
        actual_dt = self._parse_hhmm(date_str, actual_raw)
        sched_txt = f"{sched_dt:%H:%M}" if sched_dt else (sched_raw if self._is_str(sched_raw) else "--:--")
        ref = sched_dt.date() if sched_dt else None

        # 状態（右端）
        change_type = row.get('変更種別', '') if self._is_str(row.get('変更種別', '')) else ''
        status_raw = row.get(status_key, '')
        status_raw = status_raw.strip() if self._is_str(status_raw) else ''
        cancelled = any(k in status_raw for k in ('欠航', '취소', 'Cancel', 'CANCEL'))
        tag = "出発済" if is_dep else "到着済"
        if cancelled:
            status = "欠航"
        elif actual_dt:
            status = f"{tag} {actual_dt:%H:%M}"
        elif self._is_str(actual_raw):
            status = f"{tag} {actual_raw.strip()}"
        elif any(k in status_raw for k in ('遅延', '지연', 'Delay')):
            status = "遅延"
        elif status_raw and not any(k in status_raw for k in ('予定', '정시', 'On Time', 'Scheduled')):
            status = status_raw
        else:
            status = "定刻"
        # 見やすい状態文（hourly_check の差分情報があれば前回値も添える）
        kind = {'新規': 'new', '時間変更': 'changed'}.get(change_type, '')
        prev_s = row.get('前回予定時間', '')
        prev_a = row.get('前回実際時間', '')
        prev_sched = prev_s.strip() if self._is_str(prev_s) and prev_s.strip() != (sched_raw or '').strip() else None
        prev_status = None
        if kind == 'changed':
            prev_status = f"{tag} {prev_a.strip()}" if self._is_str(prev_a) else "定刻"
        status = self._pretty_status(status, sched_txt, is_dep, prev_status, prev_sched, kind)

        # 名古屋側の時刻
        base = actual_dt or sched_dt
        if cancelled or base is None:
            ngo_dt = None
        elif is_dep:
            ngo_dt = base + timedelta(minutes=self.FLIGHT_MIN_ICN_NGO)
        else:
            ngo_dt = base - timedelta(minutes=self.FLIGHT_MIN_NGO_ICN)

        # 経路
        code, via = self._airport_code(row.get(loc_key, ''))
        if is_dep:
            route = "ICN → NGO" + (f" → {code}" if code and code != 'NGO' else "")
        else:
            route = (f"{code} → " if code and code != 'NGO' else "") + "NGO → ICN"

        # 1 便 = 埋め込みフィールド 1 枠
        badge = {"新規": "🆕 ", "時間変更": "🔔 "}.get(change_type, "")
        icon = "🛫" if is_dep else "🛬"
        fcode = self._flight_code(row.get('便名', ''))
        name = f"{badge}{icon} {fcode} ｜ {self._day_label(date_str, today)}"
        icn_line = f"ICN {self._fmt_md(sched_dt)} {sched_txt} KST"
        ngo_line = "NGO --/-- --:-- JST" if ngo_dt is None else f"NGO {self._fmt_md(ngo_dt)} {ngo_dt:%H:%M} JST (推定)"
        if is_dep:
            times = [f"`🛫 {icn_line}`", f"`🛬 {ngo_line}`"]
        else:
            times = [f"`🛫 {ngo_line}`", f"`🛬 {icn_line}`"]
        value = "\n".join([route, *times, status])
        return {"name": name[:256], "value": value[:1024], "inline": False}

    @staticmethod
    def _mins_diff(a, b):
        """'04:37' - '04:35' → +2（日またぎは ±12h 以内で補正）"""
        try:
            ha, ma = map(int, a[:5].split(":")); hb, mb = map(int, b[:5].split(":"))
        except ValueError:
            return None
        d = (ha * 60 + ma) - (hb * 60 + mb)
        if d > 720:
            d -= 1440
        elif d < -720:
            d += 1440
        return d

    def _pretty_status(self, status, sched_txt, is_dep, prev_status, prev_sched, kind):
        """'定刻' / '出発済 04:37' / '遅延' / '欠航' / その他 → 見やすい表示
        例: ✅ 出発済み 04:37（予定 04:35、+2分） / 🟢 定刻どおり
        """
        s = status.strip()
        tag = "出発" if is_dep else "到着"

        def delta(tm):
            d = self._mins_diff(tm, sched_txt)
            if d is None:
                return ""
            return "、定刻" if d == 0 else f"、{d:+d}分"

        if s == "定刻":
            line = "🟢 定刻どおり"
        elif s.startswith(("出発済", "到着済")):
            actual = s.split(" ", 1)[1] if " " in s else ""
            line = f"✅ {tag}済み {actual}（予定 {sched_txt}{delta(actual)}）" if actual else f"✅ {tag}済み"
        elif s == "遅延":
            line = "🟠 遅延"
        elif s == "欠航":
            line = "🔴 欠航"
        else:
            line = f"🔵 {s}"
        if kind == "new":
            line += "\n🆕 新しく追加された便"
        elif kind == "changed":
            if prev_sched:
                line += f"\n🔔 前回: 予定 {prev_sched}・{prev_status or '?'}"
            else:
                line += f"\n🔔 前回: {prev_status or '?'}"
        return line

    def _fmt_md(self, d):
        """11/09(月) 形式"""
        return "--/--" if d is None else f"{d:%m/%d}({self.WEEKDAY_JA[d.weekday()]})"

    @staticmethod
    def _ngo_time_suffix(txt):
        """'05:40*+1' → ' (翌日・推定)'"""
        parts = []
        if "+1" in txt:
            parts.append("翌日")
        elif "-1" in txt:
            parts.append("前日")
        if "*" in txt:
            parts.append("推定")
        return f" ({'・'.join(parts)})" if parts else ""

    def _build_fields(self, df, flight_type, today):
        """便ごとのフィールド一覧（日付・予定時刻順）"""
        sched_key = '出発時間（予定）' if flight_type == 'departure' else '到着時間（予定）'
        fields, cur = [], None
        if '取得日' in df.columns:
            df = df.sort_values(['取得日', sched_key], kind='stable') if sched_key in df.columns else df.sort_values('取得日')
        for _, row in df.iterrows():
            fields.append(self._format_row(row, flight_type, today))
        return fields

    @staticmethod
    def _fields_to_text(fields):
        if not fields:
            return "  該当便なし"
        out = []
        for f in fields:
            if f["value"] == "\u200b":
                out.append(f" {f['name']}")
            else:
                out.append(f"  {f['name']}\n" + "\n".join("    " + l for l in f["value"].splitlines()))
        return "\n".join(out)

    def send_discord_notification(self, df, start_date, end_date, airport='NGO', flight_type='departure'):
        """
        ---------------------------------------------------------------------
        メソッド概要：  Discordに通知を送信（Changi 通知と共通の表形式）
        - 出発便 = 青 / 到着便 = 緑 の embed、1 便 1 行の等幅テーブル
        - 列: 出発地 出発時刻 | 便名 | 到着地 到着時刻 | 状態
        - 名古屋側の時刻は標準所要時間からの推定（* 付き）
        - 4000 字ごとに embed を分割、10 embeds/message で送信
        ----------------------------------------------------------------------
        Args:
            df (pd.DataFrame): 送信するデータ
            start_date (str): 開始日 (YYYYMMDD)
            end_date (str): 終了日 (YYYYMMDD)
            airport (str): 空港コード (デフォルト: NGO)
            flight_type (str): フライトタイプ ('departure' or 'arrival')
        ---------------------------------------------------------------------
        Returns:
            bool: 全バッチ送信成功時True
        ---------------------------------------------------------------------
        Notes:
            - revision       v3.00 (2026/11/08) - Changi 通知と共通の表形式に変更
        ---------------------------------------------------------------------
        """
        if not self.discord_webhook_url:
            print("エラー: Discord Webhook URLが設定されていません")
            print("環境変数 DISCORD_WEBHOOK_URL を設定するか、初期化時に指定してください")
            return False

        if df is None or len(df) == 0:
            print("送信するデータがありません")
            return False

        try:
            is_dep = (flight_type == 'departure')
            today = datetime.now().date()
            has_change_type = '変更種別' in df.columns
            color = self._color('DISCORD_COLOR_DEP', 0x3B82F6) if is_dep else self._color('DISCORD_COLOR_ARR', 0x22C55E)
            route = f"ICN → {airport}" if is_dep else f"{airport} → ICN"
            kind = "出発便" if is_dep else "到着便"
            what = "変更" if has_change_type else ""
            title = f"{kind}  {route}  ({len(df)} 件{what})"
            period = f"{self._day_label(start_date, today)} 〜 {self._day_label(end_date, today)}"

            fields = self._build_fields(df, flight_type, today)
            print(self._fields_to_text(fields))
            embeds = [{"title": title if i == 0 else f"{title} （続き）", "color": color, "fields": fields[i:i + 24]}
                      for i in range(0, len(fields), 24)] or [{"title": title, "description": "該当便なし", "color": color}]
            embeds[-1]["footer"] = {
                "text": f"KST=韓国時間 / JST=日本時間（同じ UTC+9） ・ 推定=標準所要時間からの概算 ・ 🔔=前回通知から変化 ・ 更新 {datetime.now():%m/%d %H:%M} JST"
            }
            content = (f"**ICN ⇄ {airport} カーゴ便{'（変更あり）' if has_change_type else ''}  |  {kind} {len(df)} 件**\n"
                       f"対象期間: {period}")

            MAX_EMBEDS_PER_MSG = 10
            print(f"  Webhook URL: {self.discord_webhook_url[:50]}...")
            print(f"  送信embed数: {len(embeds)}")
            success = True
            for batch_start in range(0, len(embeds), MAX_EMBEDS_PER_MSG):
                batch = embeds[batch_start:batch_start + MAX_EMBEDS_PER_MSG]
                payload = {"embeds": batch}
                if batch_start == 0:
                    payload["content"] = content
                response = requests.post(
                    self.discord_webhook_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                if response.status_code == 429:
                    time.sleep(float(response.headers.get('Retry-After', '2')))
                    response = requests.post(self.discord_webhook_url, json=payload, timeout=10)
                batch_num = batch_start // MAX_EMBEDS_PER_MSG + 1
                if response.status_code in (200, 204):
                    print(f"✓ Discord通知送信成功（バッチ {batch_num}）")
                else:
                    print(f"✗ エラー: Discord通知送信失敗（バッチ {batch_num}）")
                    print(f"  ステータスコード: {response.status_code}")
                    print(f"  レスポンス: {response.text}")
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


# ======================================================================================#
# @function name:   main
# @function start
def main():
    """
    ---------------------------------------------------------------------
    関数概要：  メイン関数
    - スクレイピングのテスト・使用例を実行
    - 動作確認用
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
# @function end
# ======================================================================================#


if __name__ == '__main__':
    main()
