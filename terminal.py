"""端末制御: サイズ取得・raw mode・カラー対応検出・ANSI定数。"""

import fcntl
import os
import shutil
import struct
import sys
import termios
import tty

from .utils import is_tty


class ANSI:
    """ANSIエスケープシーケンス定数。"""

    RESET = "\x1b[0m"
    HOME = "\x1b[H"
    CLEAR = "\x1b[2J"
    HIDE_CURSOR = "\x1b[?25l"
    SHOW_CURSOR = "\x1b[?25h"
    ENTER_ALT = "\x1b[?1049h"  # 代替画面へ切り替え
    LEAVE_ALT = "\x1b[?1049l"  # 代替画面から復帰


def get_terminal_size() -> tuple[int, int]:
    """端末の (列数, 行数) を取得する。ttyでなければ (80, 24)。"""
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


# 文字セルの 高さ/幅 比のデフォルト値（一般的な等幅フォント ≒ 2.0）
DEFAULT_CELL_RATIO = 2.0


def cell_ratio_from_size(
    rows: int, cols: int, xpixel: int, ypixel: int
) -> float | None:
    """ウィンドウのピクセルサイズから文字セルの 高さ/幅 比を求める。

    端末がピクセルサイズを返さない（0）場合や、明らかに異常な値の場合は None。
    """
    if not (rows and cols and xpixel and ypixel):
        return None
    ratio = (ypixel / rows) / (xpixel / cols)
    if not 0.5 <= ratio <= 6.0:
        return None
    return ratio


def detect_cell_ratio(fallback: float = DEFAULT_CELL_RATIO) -> float:
    """端末の文字セルの 高さ/幅 比を実測する（取れなければ fallback）。

    描画領域を正確な4:3にするために使う。TIOCGWINSZ が返すウィンドウの
    ピクセルサイズから1セルあたりの大きさを求める。tty でない場合や
    ピクセルサイズを返さない端末（多くの端末）では fallback を使う。
    """
    try:
        buf = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols, xpixel, ypixel = struct.unpack("HHHH", buf)
    except Exception:
        return fallback
    ratio = cell_ratio_from_size(rows, cols, xpixel, ypixel)
    return fallback if ratio is None else ratio


def detect_color_mode(force: bool = False, disable: bool = False) -> str:
    """端末のカラー対応を検出して "truecolor"|"256"|"basic"|"mono" を返す。

    優先順位: 24-bit TrueColor → 256 color → ANSI basic → monochrome
    """
    if disable or os.environ.get("NO_COLOR"):
        return "mono"
    ct = os.environ.get("COLORTERM", "").lower()
    term = os.environ.get("TERM", "")
    if force:
        if ct in ("truecolor", "24bit"):
            return "truecolor"
        if "256color" in term:
            return "256"
        if term and term != "dumb":
            return "basic"
        return "mono"
    if ct in ("truecolor", "24bit"):
        return "truecolor"
    if "256color" in term:
        return "256"
    if term and term != "dumb":
        return "basic"
    return "mono"


class RawTerminal:
    """stdin を raw/cbreak モードにするコンテキストマネージャ。

    終了時（例外発生時も含む）に必ず端末設定を復元する。
    tty でない場合は何もしない。
    """

    def __init__(self, stream=None) -> None:
        self.stream = stream if stream is not None else sys.stdin
        self.fd = self.stream.fileno()
        self.active = False
        self.old = None

    def __enter__(self) -> "RawTerminal":
        if is_tty(self.stream):
            self.old = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
            self.active = True
        return self

    def __exit__(self, *exc) -> None:
        self.restore()

    def restore(self) -> None:
        if self.active and self.old is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
            except Exception:
                pass
            self.active = False


def pad_line(text: str, width: int) -> str:
    """行を指定幅まで空白で埋める（それ以上ならそのまま）。"""
    n = width - len(text)
    return text if n <= 0 else text + " " * n