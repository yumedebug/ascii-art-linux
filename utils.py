"""共通ユーティリティ: 時間・サイズ整形、ツール検出、共通例外。"""

import os
import shutil
import time


class AppError(Exception):
    """ユーザーが原因を理解できるエラーメッセージを持つ例外。

    hint には対処方法（インストール方法など）を入れる。
    """

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def monotonic() -> float:
    return time.monotonic()


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def format_time(seconds: float) -> str:
    """秒数を MM:SS（1時間以上なら H:MM:SS）形式にする。"""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def human_size(num: float) -> str:
    """バイト数を人間に読みやすい形式にする。"""
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024.0 or unit == "TB":
            return f"{int(num)} B" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def find_tool(name: str) -> str | None:
    return shutil.which(name)


def require_tool(name: str, hint: str = "") -> str:
    path = shutil.which(name)
    if not path:
        raise AppError(f"必要なツール「{name}」が見つかりません。", hint=hint)
    return path


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False