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
        
        current = start
        while current <= end:
            date_str = current.strftime('%Y%m%d')
            print(f"\n--- {date_str} のデータを取得中 ---")
            
            df = self.scrape(date_str, airport, output_format=None, save_html=False, flight_type=flight_type)
            if df is not None and len(df) > 0:
                df['取得日'] = date_str
                all_data.append(df)
            
            current += timedelta(days=1)
            time.sleep(2)  # サーバーに負荷をかけないよう待機
        
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
    def send_discord_notification(self, df, start_date, end_date, airport='NGO', flight_type='departure'):
        """
        ---------------------------------------------------------------------
        メソッド概要：  Discordに通知を送信
        - Webhook経由でフライト情報を送信
        - ヘッダーembedと日付ごとのembedにフライトをfieldとして表示
        - 10 embeds/message、25 fields/embed の制限に対応して複数回送信
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
            - author         GitHub Copilot
            - revision       v2.00 (2026/03/15) - embed/field形式にリファクタリング
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
            # ── フライトタイプ別設定 ──────────────────────────────────────────
            if flight_type == 'departure':
                emoji    = "🛫"
                type_ja  = "出発"
                time_key_scheduled = '出発時間（予定）'
                time_key_actual    = '出発時間（実際）'
                location_key       = '目的地'
                status_key         = '出発状態'
                color = 3447003    # 青
            else:
                emoji    = "🛬"
                type_ja  = "到着"
                time_key_scheduled = '到着時間（予定）'
                time_key_actual    = '到着時間（実際）'
                location_key       = '出発地'
                status_key         = '到着状態'
                color = 15844367   # 金

            has_change_type = '変更種別' in df.columns if hasattr(df, 'columns') else False

            def fmt_date(d):
                """YYYYMMDD → YYYY/MM/DD"""
                return f"{d[:4]}/{d[4:6]}/{d[6:]}"

            # ── 1フライト分の embed field (name, value) を生成 ───────────────
            def build_flight_field(row):
                change_type = row.get('変更種別', '')
                change_icon = {'新規': '🆕', '時間変更': '⏰'}.get(change_type, '✈️')

                flight_num = row.get('便名', 'N/A')
                airline    = row.get('航空会社', 'N/A')
                badge      = f"[{change_type}] " if change_type else ""
                field_name = f"{change_icon} {badge}{flight_num}  ({airline})"

                lines = []

                # 目的地 / 出発地
                location = row.get(location_key, '')
                if location and location != 'N/A':
                    loc_label = "目的地" if flight_type == 'departure' else "出発地"
                    lines.append(f"📍 **{loc_label}**: {location}")

                # 時間情報
                scheduled = row.get(time_key_scheduled, '')
                actual    = row.get(time_key_actual, '')

                if change_type == '時間変更':
                    prev_scheduled = row.get('前回予定時間', '')
                    prev_actual    = row.get('前回実際時間', '')

                    if prev_scheduled and prev_scheduled != scheduled:
                        lines.append(f"🕐 予定: ~~{prev_scheduled}~~ → **{scheduled}**")
                    elif scheduled:
                        lines.append(f"🕐 予定: {scheduled}")

                    if prev_actual and prev_actual != actual:
                        new_act = f"**{actual}**" if actual and isinstance(actual, str) else "未定"
                        lines.append(f"⏰ 実際: ~~{prev_actual}~~ → {new_act}")
                    elif actual and isinstance(actual, str):
                        lines.append(f"⏰ 実際: **{actual}**")
                else:
                    if scheduled:
                        lines.append(f"🕐 予定: {scheduled}")
                    if actual and isinstance(actual, str) and actual != scheduled:
                        lines.append(f"⏰ 実際: **{actual}**")

                # 駐機場
                gate = row.get('駐機場', '')
                if gate and gate != 'N/A' and isinstance(gate, str):
                    lines.append(f"🚪 駐機場: {gate}")

                # ターミナル
                terminal = row.get('ターミナル', '')
                if terminal and terminal != 'N/A' and isinstance(terminal, str):
                    lines.append(f"🏢 ターミナル: {terminal}")

                # 状態
                status = row.get(status_key, '')
                if status and isinstance(status, str):
                    status_icon = "✅" if type_ja in status else "⏳"
                    lines.append(f"{status_icon} 状態: {status}")

                field_value = "\n".join(lines) if lines else "情報なし"
                return field_name[:256], field_value[:1024]

            # ── embedリストを構築 ──────────────────────────────────────────────
            MAX_FIELDS_PER_EMBED = 25
            MAX_EMBEDS_PER_MSG   = 10

            count_label = "変更件数" if has_change_type else "取得件数"
            header_embed = {
                "title":       f"{emoji} 仁川国際空港 貨物{type_ja}スケジュール",
                "description": (
                    f"**期間**: {fmt_date(start_date)} 〜 {fmt_date(end_date)}\n"
                    f"**空港**: {airport}\n"
                    f"**{count_label}**: {len(df)}件"
                ),
                "color": color,
            }
            all_embeds = [header_embed]

            def new_date_embed(title):
                return {"title": title, "color": color, "fields": []}

            if '取得日' in df.columns:
                for date, group in df.groupby('取得日'):
                    current_embed = new_date_embed(f"📅 {fmt_date(date)}")
                    part = 1
                    for _, row in group.iterrows():
                        if len(current_embed["fields"]) >= MAX_FIELDS_PER_EMBED:
                            all_embeds.append(current_embed)
                            part += 1
                            current_embed = new_date_embed(f"📅 {fmt_date(date)} （続き {part}）")
                        fname, fval = build_flight_field(row)
                        current_embed["fields"].append({"name": fname, "value": fval, "inline": False})
                    if current_embed["fields"]:
                        all_embeds.append(current_embed)
            else:
                current_embed = new_date_embed("📅 スケジュール")
                part = 1
                for _, row in df.iterrows():
                    if len(current_embed["fields"]) >= MAX_FIELDS_PER_EMBED:
                        all_embeds.append(current_embed)
                        part += 1
                        current_embed = new_date_embed(f"📅 スケジュール （続き {part}）")
                    fname, fval = build_flight_field(row)
                    current_embed["fields"].append({"name": fname, "value": fval, "inline": False})
                if current_embed["fields"]:
                    all_embeds.append(current_embed)

            # フッターは最後のembedに付与
            all_embeds[-1]["footer"] = {
                "text": f"取得日時: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
            }

            # ── 10 embeds ずつ送信 ────────────────────────────────────────────
            print(f"  Webhook URL: {self.discord_webhook_url[:50]}...")
            print(f"  送信embed数: {len(all_embeds)}")

            success = True
            for batch_start in range(0, len(all_embeds), MAX_EMBEDS_PER_MSG):
                batch = all_embeds[batch_start:batch_start + MAX_EMBEDS_PER_MSG]
                response = requests.post(
                    self.discord_webhook_url,
                    json={"embeds": batch},
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                batch_num = batch_start // MAX_EMBEDS_PER_MSG + 1
                if response.status_code == 204:
                    print(f"✓ Discord通知送信成功（バッチ {batch_num}）")
                else:
                    print(f"✗ エラー: Discord通知送信失敗（バッチ {batch_num}）")
                    print(f"  ステータスコード: {response.status_code}")
                    print(f"  レスポンス: {response.text}")
                    success = False

                # レート制限を避けるため、次のバッチ前に少し待機
                if batch_start + MAX_EMBEDS_PER_MSG < len(all_embeds):
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
