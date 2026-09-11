"""エントリポイント。

- パッケージとして: python3 -m ascii_player
- スクリプトとして: python3 ascii_player/__main__.py（直接実行も可能）
"""

import os
import sys

try:
    from .cli import main
except ImportError:  # 直接実行された場合（相対import不可）
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from ascii_player.cli import main

if __name__ == "__main__":
    sys.exit(main())