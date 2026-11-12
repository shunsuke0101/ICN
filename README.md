# 仁川国際空港 貨物出発・到着時刻表スクレイピングプログラム

仁川国際空港の貨物出発・到着時刻表をスクレイピングして、CSV、JSON、Excelファイルとして保存するPythonプログラムです。

## 機能

- 指定した日付の貨物出発・到着スケジュールを取得
- 複数日のデータを一括取得
- CSV、JSON、Excel形式での出力に対応
- 空港コードを指定可能
- **時間データの完全取得**
  - 📅 **予定時間**: 出発/到着の当初の予定時刻
  - 🕐 **最新時間**: サイトが表示している最新の時刻（予定から変わった場合のみ）。
    出発/到着済みなら**実績**、まだなら**見込み**（遅延・時刻変更）。どちらかは状態欄で判定
- Discord Webhookへの通知機能
- **定期実行機能**
  - 毎日22時に7日分のデータ（出発便・到着便）をすべて通知（一覧通知）
  - 1時間ごとに変更をチェックし、**変更があった便だけを 1 便 = 1 メッセージで個別に通知**
- **変更検出**（便名 + 日付で照合）
  - 🔔 **時刻・状態の変更**: 予定時刻 / 最新時刻（見込み・実績）/ 状態（遅延・出発・到着・欠航）
  - 🆕 **追加**: すでに監視していた日付に新しい便が現れた
  - 🗑️ **削除**: 監視中の日付から便が消えた（`.env` の `ICN_NOTIFY_REMOVED=0` で通知しない）
  - 🔔 **日付変更**: 同じ便名の「削除」と「追加」が前後 1 日以内に同時に起きたら 1 件にまとめる
  - 監視期間が 1 日進んで見えるようになった便・取得に失敗した日付の便・駐機場の割当は通知しない


## Discord 通知フォーマット（2026/11/12 更新）

通知は 2 種類あります。どちらも 1 便分の枠の書式は共通です（Changi（SIN）通知と同じ並び）。

| 種類 | いつ | 内容 |
|---|---|---|
| 一覧通知 | 毎日 22 時（`daily_notify.py`）／ `hourly_check.py` の初回実行 | 今日から 7 日分の全便を 1 メッセージ（出発便 = 青、到着便 = 緑） |
| 個別通知 | 1 時間ごと（`hourly_check.py`）、変更があったときだけ | **変更があった便を 1 便 = 1 メッセージ** |

### 個別通知（変更があった便）

```
K4 217 ｜ ICN → NGO ｜ 11/13(金)              ← 本文（スマホの通知にもここが出る）
🟠 遅延 → 18:20（予定 11:35、+405分）

▌🔔 🛫 K4 217 ｜ 明日 11/13 (金)               ← 埋め込み（出発 = 青 / 到着 = 緑）
▌ICN → NGO → CVG
▌`🛫 ICN 11/13(金) 18:20 KST (見込み)`
▌`🛬 NGO 11/13(金) 20:15 JST (推定)`
▌`ICN Cargo(N) ・ 駐機場 642`
▌🟠 遅延 → 18:20（予定 11:35、+405分）
▌🔔 前回: 🟠 遅延 → 17:05（予定 11:35、+330分）
```

埋め込みの最後の行が変更内容です。

| 最後の行 | 意味 |
|---|---|
| 🔔 前回: … | 時刻・状態が変わった（前回チェック時の状態） |
| 🔔 日付変更 ・ 前回: 11/17(火) 22:10 | 同じ便が別の日に移った |
| 🆕 新しく追加された便 | 監視中の日付に新しく現れた便 |
| 🗑️ スケジュールから削除された便 | 監視中の日付から消えた便（枠の内容は消える直前の状態） |

- 通知に失敗した便は、次回のチェックでもう一度通知します
- 監視期間は**前日〜6 日後**（日付をまたいで出発・到着した便も拾うため前日を含む）

### 一覧通知

```
ICN ⇄ NGO カーゴ便  |  出発 6 件 / 到着 5 件
対象期間: 今日 11/12 (木) 〜 11/18 (水)

▌出発便  ICN → NGO  (6 件)                 ← 青
▌ 🛫 K4 217 ｜ 明日 11/13 (金)
▌ ICN → NGO → CVG
▌ `🛫 ICN 11/13(金) 17:05 KST (見込み)`
▌ `🛬 NGO 11/13(金) 19:00 JST (推定)`
▌ `ICN Cargo(N) ・ 駐機場 642`
▌ 🟠 遅延 → 17:05（予定 11:35、+330分）
▌
▌ 🛫 K4 219 ｜ 明日 11/13 (金)
▌ ICN → NGO → CVG
▌ `🛫 ICN 11/13(金) 23:15 KST`
▌ `🛬 NGO 11/14(土) 01:10 JST (推定)`
▌ `ICN Cargo(N) ・ 駐機場 677`
▌ 🟢 定刻どおり
▌
▌到着便  NGO → ICN  (5 件)                 ← 緑
▌ 🛬 JL 6749 ｜ 今日 11/12 (木)
▌ NGO → ICN
▌ `🛫 NGO 11/12(木) 01:56 JST (推定)`
▌ `🛬 ICN 11/12(木) 04:01 KST (実績)`
▌ `ICN Cargo(S) ・ 駐機場 609`
▌ ✅ 到着済み 04:01（予定 04:15、-14分）
```
1 便 = 1 枠を縦に並べます（便と便の間は 1 行空き）。
各枠: 見出し = 便名と予定日、1 行目 = 経路、2〜3 行目 = 出発/到着の日付・時刻（各空港の現地日時、NGO は日本時間）、4 行目 = ICN 側のターミナル・駐機場（未割当は `--`。通常は出発当日に割り当てられる）、5 行目 = 状態。

- 便が 1 件も無い方向は、埋め込みに「該当便なし」と表示します

### 時刻と状態の読み方（2026/11/12 に全面見直し）

仁川空港サイトの時刻欄は「最新時刻」と「当初の予定時刻」の 2 段になっていて、最新時刻が
**実績なのか見込みなのかは状態欄で決まります**。以前は最新時刻があれば一律「出発済み」と
表示していましたが、現在は次のように判定します。

| サイトの状態欄 | 最新時刻の意味 | 状態の表示 | ICN の時刻行 |
|---|---|---|---|
| 出発 / 到着 | 実績 | ✅ 出発済み 22:40（予定 22:00、+40分） | 実績時刻 `(実績)` |
| 遅延 | 見込み（まだ出発/到着していない） | 🟠 遅延 → 17:05（予定 11:35、+330分） | 見込み時刻 `(見込み)` |
| （空欄）で最新時刻あり | 見込み（時刻変更） | 🟡 時刻変更 → 04:02（予定 04:15、-13分） | 見込み時刻 `(見込み)` |
| （空欄）で最新時刻なし | — | 🟢 定刻どおり | 予定時刻 |
| 欠航 | — | 🔴 欠航 | 予定時刻（NGO 側は `--:--`） |
| その他の文言 | 見込み | 🔵 サイトの状態文をそのまま表示 | 見込み時刻 `(見込み)` |

- ICN の時刻行は「実績 > 見込み > 予定」の順で、分かっている最新の時刻を表示します
- 最新時刻は時刻（HH:MM）しか無いため、予定時刻との前後関係から日付を決めます
  （予定 00:05 → 実績 23:51 は**前日**、予定 22:00 → 見込み 01:30 は**翌日**。
  予定より 6 時間超早い／18 時間超遅い時刻は日付が違うものとして扱う）。
  予定日と違う日になる場合は状態の行にも日付を出します（例: `🟠 遅延 → 11/15(日) 01:30（予定 22:00、+210分）`）
- `推定` = 名古屋側の時刻。ICN の時刻行の時刻 ± 標準所要時間（ICN→NGO 115 分 / NGO→ICN 125 分）で算出。
  `.env` の `FLIGHT_MINUTES_ICN_NGO` / `FLIGHT_MINUTES_NGO_ICN` で変更可
- `ICN → NGO → CVG` = 名古屋経由で最終目的地が CVG
- 色は `.env` の `DISCORD_COLOR_DEP` / `DISCORD_COLOR_ARR`（16 進）で変更可
- 高速化: 日付ごとの取得を 3 並列にし、1 日ごとの 2 秒待機を廃止（7 日分 × 出発/到着 で従来 30 秒以上 → 数秒）
- 駐機場・状態は列番号ではなくクラス名（`div.jugi` / `div.state`）で取得（2026/11/09）。サイトの列構成が出発便 col5/col6・到着便 col6/col7 と異なるため、以前は到着便の駐機場が取れず状態列もずれていた

### `.env` の設定項目

| 項目 | 既定値 | 内容 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | （必須） | 通知先の Webhook URL |
| `ICN_NOTIFY_REMOVED` | `1` | `0` にすると「スケジュールから削除された便」を通知しない |
| `FLIGHT_MINUTES_ICN_NGO` / `FLIGHT_MINUTES_NGO_ICN` | `115` / `125` | 名古屋側の時刻の推定に使う所要時間（分） |
| `DISCORD_COLOR_DEP` / `DISCORD_COLOR_ARR` | `3B82F6` / `22C55E` | 埋め込みの色（16 進） |

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

# 今日の出発便データを取得してCSVで保存
df_departure = scraper.scrape(output_format='csv', flight_type='departure')

# 今日の到着便データを取得してCSVで保存
df_arrival = scraper.scrape(output_format='csv', flight_type='arrival')
```

### 特定の日付のデータを取得

```python
# 2024年11月29日の出発便データを取得
df_departure = scraper.scrape(
    date_str='20241129', 
    airport='NGO', 
    output_format='json',
    flight_type='departure'
)

# 2024年11月29日の到着便データを取得
df_arrival = scraper.scrape(
    date_str='20241129', 
    airport='NGO', 
    output_format='json',
    flight_type='arrival'
)
```

### 複数日のデータを一括取得

```python
# 2024年12月1日から7日までの出発便データを取得
df_departure = scraper.scrape_multiple_dates(
    '20241201', 
    '20241207', 
    airport='NGO', 
    output_format='excel',
    flight_type='departure'
)

# 2024年12月1日から7日までの到着便データを取得
df_arrival = scraper.scrape_multiple_dates(
    '20241201', 
    '20241207', 
    airport='NGO', 
    output_format='excel',
    flight_type='arrival'
)
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

# 出発便データを取得
df_departure = scraper.scrape_multiple_dates(
    start_date, 
    end_date, 
    airport='NGO', 
    flight_type='departure'
)

# 到着便データを取得
df_arrival = scraper.scrape_multiple_dates(
    start_date, 
    end_date, 
    airport='NGO', 
    flight_type='arrival'
)

# Discordに通知（出発便・到着便を 1 メッセージで送信）
scraper.send_discord_notification(df_departure, df_arrival, start_date, end_date, 'NGO')
```

取得したデータの列（出発便の場合。到着便は「出発」→「到着」、「目的地」→「出発地」）:
`出発時間（予定）` / `出発時間（最新）` / `目的地` / `便名` / `航空会社` / `ターミナル` / `駐機場` / `出発状態` / `取得日`

※ 2026/11/12 に列名 `出発時間（実際）` / `到着時間（実際）` を `…（最新）` に変更しました
（実績とは限らず、遅延・時刻変更の見込み時刻のこともあるため）。実績か見込みかは
`IncheonCargoScraper.flight_state(row, flight_type)` の `phase` で判定できます。

### 定期実行機能

#### 1. 毎日22時に7日分のデータ（出発便・到着便）をすべて通知

```powershell
python daily_notify.py
```

- 出発便と到着便の両方のデータを取得
- 出発便・到着便を 1 メッセージにまとめてDiscord通知を送信
- 変更検出用のキャッシュには触りません（2026/11/12 変更。キャッシュは `hourly_check.py` だけが管理）

このスクリプトは毎日22時に実行することで、その日から7日分のフライトスケジュールをすべてDiscordに通知します。

#### 2. 1時間ごとに変更をチェックして通知

```powershell
python hourly_check.py
```

このスクリプトは1時間ごとに実行され、前回のデータと比較して、**変更があった便だけを 1 便 = 1 メッセージで** Discord に通知します。

- 監視期間は前日〜6 日後。出発便と到着便をそれぞれ前回データと比較
- 変更の種類（便名 + 日付で照合）:
  - 🔔 **時刻・状態の変更**: 予定時刻 / 最新時刻（見込み・実績）/ 状態（遅延・出発・到着・欠航）のどれかが変わった
  - 🆕 **追加**: 前回すでに監視していた日付に新しい便が現れた
  - 🗑️ **削除**: 監視中の日付から便が消えた（出発/到着済み・欠航の便は対象外。`ICN_NOTIFY_REMOVED=0` で通知しない）
  - 🔔 **日付変更**: 同じ便名の「削除」と「追加」が前後 1 日以内に同時に起きた場合
- 通知しないもの: 監視期間が進んで見えるようになった便、取得に失敗した日付の便（前回データを持ち越して次回比較）、駐機場・ターミナルの割当
- 初回実行（キャッシュなし）のときだけ、対象期間の全便を一覧で 1 回通知して基準データを保存
- 通知に失敗した便は前回データを残し、次回のチェックで再通知
- キャッシュファイル: `log/last_data_cache.json`（出発便）/ `log/last_data_cache_arrival.json`（到着便）。
  2026/11/12 から形式を変更（監視済みの日付を一緒に保存）。以前の形式のファイルはそのまま読み込めます
- 終了コード: 0 = 正常 / 1 = データ取得に全て失敗、または通知に失敗した便あり

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
- `output_format` (str, optional): 出力形式 ('csv', 'json', 'excel')。Noneの場合は保存しない
- `flight_type` (str, optional): フライトタイプ ('departure' または 'arrival')。デフォルト: 'departure'

### scrape_multiple_dates() メソッド

- `start_date` (str): 開始日 (YYYYMMDD形式)
- `end_date` (str): 終了日 (YYYYMMDD形式)
- `airport` (str, optional): 空港コード (デフォルト: 'NGO')
- `output_format` (str, optional): 出力形式 ('csv', 'json', 'excel')。Noneの場合は保存しない
- `flight_type` (str, optional): フライトタイプ ('departure' または 'arrival')。デフォルト: 'departure'

### send_discord_notification() メソッド

- `df_departure` (pd.DataFrame): 出発便データ（空・None の場合は「該当便なし」と表示）
- `df_arrival` (pd.DataFrame): 到着便データ（空・None の場合は「該当便なし」と表示）
- `start_date` (str): 開始日 (YYYYMMDD形式)
- `end_date` (str): 終了日 (YYYYMMDD形式)
- `airport` (str, optional): 空港コード (デフォルト: 'NGO')

※ 2026/11/11 に引数を変更しました（旧: `df, start_date, end_date, airport, flight_type`）。

### send_change_notifications() メソッド

変更があった便を 1 便 = 1 メッセージで通知します（`hourly_check.py` が使用）。

- `changes` (list[dict]): 変更情報のリスト。各要素は
  - `flight_type`: `'departure'` または `'arrival'`
  - `kind`: `'changed'`（時刻・状態の変更）/ `'new'`（追加）/ `'moved'`（日付変更）/ `'removed'`（削除）
  - `row`: 今回のデータ行（`removed` は前回のデータ行）
  - `prev`: 前回のデータ行（`changed` / `moved` のとき）
- `airport` (str, optional): 空港コード (デフォルト: 'NGO')
- 戻り値: `changes` と同じ並びの送信結果（`list[bool]`）

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
3. データが存在しない場合は空のDataFrameが返されます（取得に失敗した場合は `scrape()` は `None` を返し、
   `scrape_multiple_dates()` は失敗した日付を `scraper.last_failed_dates` に記録します）
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

