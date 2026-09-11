#!/usr/bin/env python3
"""開発用エントリポイント: python3 main.py で起動する。"""

import os
import sys

# プロジェクトルートを sys.path に追加して ascii_player パッケージを import 可能にする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ascii_player.cli import main

if __name__ == "__main__":
    sys.exit(main())