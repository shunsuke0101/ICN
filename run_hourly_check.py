# coding: utf_8
# -----------------------------------------------------------------------------------#
# @file           run_hourly_check.py
# @brief          時間ごとチェック実行ラッパー（Windows Task Scheduler用）
# @author         GitHub Copilot
# @date           2025/11/01
# $Version:       1.00
# $Revision:      2025/11/01 - 初期実装
# @note           hourly_check.pyをUTF-8エンコーディングで実行
#                 Windows環境でのコンソール出力文字化け対策
# @attention      Windows Task Schedulerから実行される想定
# @par            History
#                 v1.00 (2025/11/01) - 初期実装
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

# hourly_check.pyをインポートして実行
from hourly_check import main

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
