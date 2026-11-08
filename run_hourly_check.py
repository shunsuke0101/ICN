# coding: utf-8
# -----------------------------------------------------------------------------------#
# @file           ICN/run_hourly_check.py
# @brief          時間ごとチェック実行ラッパー（Windows Task Scheduler用）
# @author         Kidera Shunsuke
# @date           2025/11/01
# $Version:       1.02
# $Revision:      2026/11/08
# @note           hourly_check.pyをUTF-8エンコーディングで実行
#                 Windows環境でのコンソール出力文字化け対策
#                 出発便と到着便の両方の変更を検出してDiscord通知
# @attention      プロジェクトのコーディングフォーマット・コメントフォーマット遵守
#                 Windows Task Schedulerから1時間ごとに実行される想定
# @par            History
#                 v1.00 (2025/11/01) - 初期実装
#                 v1.01 (2025/11/01) - 到着便データ取得・変更検出機能追加
#                 v1.02 (2026/11/08) - コメントフォーマットの統一
# Copyright (c) 2025-2026. All Rights reserved.
#
# -----------------------------------------------------------------------------------#

# 標準ライブラリ
import sys                                         # 標準出力・終了コード
import os                                          # カレントディレクトリ変更
from pathlib import Path                           # パス操作

# UTF-8出力を設定
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# スクリプトのディレクトリに移動
os.chdir(Path(__file__).parent)

# hourly_check.pyをインポートして実行
from hourly_check import main                       # 実処理のエントリポイント

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
