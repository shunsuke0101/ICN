# coding: utf_8
# -----------------------------------------------------------------------------------#
# @file           run_daily_notify.py
# @brief          毎日定時通知実行ラッパー（Windows Task Scheduler用）
# @author         GitHub Copilot
# @date           2025/11/01
# $Version:       1.01
# $Revision:      2025/11/01 - 到着便対応追加
# @note           daily_notify.pyをUTF-8エンコーディングで実行
#                 Windows環境でのコンソール出力文字化け対策
#                 出発便と到着便の両方のデータを取得してDiscord通知
# @attention      Windows Task Schedulerから毎日22:00に実行される想定
# @par            History
#                 v1.00 (2025/11/01) - 初期実装
#                 v1.01 (2025/11/01) - 到着便データ取得機能追加
# Copyright (c) 2025. All Rights reserved.
#
# -----------------------------------------------------------------------------------#

import sys
import os
from pathlib import Path

# UTF-8出力を設定
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# スクリプトのディレクトリに移動
os.chdir(Path(__file__).parent)

# daily_notify.pyをインポートして実行
from daily_notify import main

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
