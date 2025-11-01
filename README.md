# 仁川国際空港 貨物出発時刻表スクレイピングプログラム

仁川国際空港の貨物出発時刻表をスクレイピングして、CSV、JSON、Excelファイルとして保存するPythonプログラムです。

## 機能

- 指定した日付の貨物出発スケジュールを取得
- 複数日のデータを一括取得
- CSV、JSON、Excel形式での出力に対応
- 空港コードを指定可能
- Discord Webhookへの通知機能
- **定期実行機能**
  - 毎日22時に7日分のデータをすべて通知
  - 1時間ごとに変更をチェックし、変更があった場合のみ通知

## 必要な環境

- Python 3.7以上
- 必要なライブラリ(requirements.txtを参照)

## インストール

1. 必要なパッケージをインストール:
```powershell
pip install -r requirements.txt
```

## 使い方

### 基本的な使い方

```python
from incheon_cargo_scraper import IncheonCargoScraper

# スクレイパーのインスタンスを作成
scraper = IncheonCargoScraper()

# 今日のデータを取得してCSVで保存
df = scraper.scrape(output_format='csv')
```

### 特定の日付のデータを取得

```python
# 2024年11月29日のデータを取得
df = scraper.scrape(date_str='20241129', airport='NGO', output_format='json')
```

### 複数日のデータを一括取得

```python
# 2024年12月1日から7日までのデータを取得
df = scraper.scrape_multiple_dates('20241201', '20241207', airport='NGO', output_format='excel')
```

### コマンドラインから実行

```powershell
python incheon_cargo_scraper.py
```

### Discord通知機能

#### 方法1: .envファイルを使用（推奨）

1. `.env.example`を`.env`にコピー:
```powershell
Copy-Item .env.example .env
```

2. `.env`ファイルを編集してWebhook URLを設定:
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_URL
```

3. スクリプトを実行:
```powershell
python notify_7days_env.py
```

#### 方法2: 7日分のデータを取得してDiscordに通知（対話式）

```powershell
python notify_7days.py
```

実行すると、Discord Webhook URLの入力を求められます。

#### 方法3: 環境変数を直接設定

```powershell
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL"
python notify_7days_env.py
```

#### Discord Webhook URLの取得方法

1. Discordサーバーの設定を開く
2. 「連携サービス」→「ウェブフック」→「新しいウェブフック」
3. ウェブフック名を設定し、通知先チャンネルを選択
4. 「ウェブフックURLをコピー」

#### プログラムから使用する場合

```python
from incheon_cargo_scraper import IncheonCargoScraper
from datetime import datetime, timedelta

# Webhook URLを指定してスクレイパーを初期化
scraper = IncheonCargoScraper(discord_webhook_url="YOUR_WEBHOOK_URL")

# データを取得
today = datetime.now()
start_date = today.strftime('%Y%m%d')
end_date = (today + timedelta(days=6)).strftime('%Y%m%d')

df = scraper.scrape_multiple_dates(start_date, end_date, airport='NGO', output_format='csv')

# Discordに通知
scraper.send_discord_notification(df, start_date, end_date, 'NGO')
```

### 定期実行機能

#### 1. 毎日22時に7日分のデータをすべて通知

```powershell
python daily_notify.py
```

このスクリプトは毎日22時に実行することで、その日から7日分のフライトスケジュールをすべてDiscordに通知します。

#### 2. 1時間ごとに変更をチェックして通知

```powershell
python hourly_check.py
```

このスクリプトは1時間ごとに実行され、前回のデータと比較して変更があった場合のみDiscordに通知します。

#### Windowsタスクスケジューラーで自動実行

1. PowerShellを**管理者として**実行

2. スケジュール設定スクリプトを実行:
```powershell
cd x:\python\ICN
.\setup_scheduler.ps1
```

3. 自動的に以下のタスクが登録されます:
   - **ICN_Daily_Notify**: 毎日22時に実行
   - **ICN_Hourly_Check**: 1時間ごとに実行

4. タスクスケジューラーで確認:
```powershell
taskschd.msc
```

#### 手動でタスクを実行してテスト

```powershell
# 毎日22時の通知をテスト
python run_daily_notify.py

# 1時間ごとのチェックをテスト
python run_hourly_check.py
```

## パラメータ

### scrape() メソッド

- `date_str` (str, optional): 日付 (YYYYMMDD形式)。Noneの場合は今日の日付
- `airport` (str, optional): 空港コード (デフォルト: 'NGO')
- `output_format` (str, optional): 出力形式 ('csv', 'json', 'excel')

### scrape_multiple_dates() メソッド

- `start_date` (str): 開始日 (YYYYMMDD形式)
- `end_date` (str): 終了日 (YYYYMMDD形式)
- `airport` (str, optional): 空港コード (デフォルト: 'NGO')
- `output_format` (str, optional): 出力形式 ('csv', 'json', 'excel')

## 空港コード例

- `NGO`: 名古屋
- `NRT`: 成田
- `KIX`: 関西
- `ICN`: 仁川 (韓国)

## 出力ファイル

ファイル名形式: `incheon_cargo_{空港コード}_{日付}_{タイムスタンプ}.{拡張子}`

例:
- `incheon_cargo_NGO_20241129_20241101_123456.csv`
- `incheon_cargo_NGO_20241129_20241101_123456.json`
- `incheon_cargo_NGO_20241129_20241101_123456.xlsx`

## 注意事項

1. サーバーに負荷をかけないよう、複数日のデータを取得する際は間隔をあけています
2. ウェブサイトの構造が変更された場合、プログラムの修正が必要になる可能性があります
3. データが存在しない場合は空のDataFrameが返されます
4. 取得したデータの利用については、仁川国際空港の利用規約を遵守してください

## トラブルシューティング

### データが取得できない場合

1. インターネット接続を確認
2. URLが正しいか確認
3. 指定した日付にデータが存在するか確認
4. サイトの構造が変更されていないか確認

### エラーが発生する場合

- `requests.exceptions.RequestException`: ネットワーク接続の問題
- `ModuleNotFoundError`: 必要なパッケージがインストールされていない
  → `pip install -r requirements.txt` を実行

## ライセンス

このプログラムは教育目的で作成されています。
商用利用の際は仁川国際空港の利用規約を確認してください。
