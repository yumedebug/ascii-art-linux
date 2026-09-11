"""キーボード入力のリアルタイム取得。

raw/cbreak モードの stdin をスレッドで監視し、矢印キーなどの
エスケープシーケンスを解釈してキューへ投入する。
"""

import os
import select
import threading

# キー名 → アクション
KEY_ACTIONS = {
    "space": "pause",
    "q": "quit",
    "esc": "quit",
    "ctrl-c": "quit",
    "left": "seek_back",
    "right": "seek_fwd",
    "up": "speed_up",
    "down": "speed_down",
    "plus": "brightness_up",
    "minus": "brightness_down",
    "m": "cycle_mode",
    "c": "cycle_color",
    "r": "reset_speed",
}

_SIMPLE_KEYS = {
    b" ": "space",
    b"q": "q",
    b"Q": "q",
    b"\x03": "ctrl-c",
    b"+": "plus",
    b"-": "minus",
    b"m": "m",
    b"M": "m",
    b"c": "c",
    b"C": "c",
    b"r": "r",
    b"R": "r",
}

_ARROW_KEYS = {
    b"A": "up",
    b"B": "down",
    b"C": "right",
    b"D": "left",
}


class KeyReader(threading.Thread):
    """stdin を監視してキーイベントを queue へ投入するデーモンスレッド。"""

    def __init__(self, fd: int, queue_, enabled: bool = True) -> None:
        super().__init__(daemon=True)
        self.fd = fd
        self.q = queue_
        self.enabled = enabled
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        if not self.enabled:
            return
        while not self._stop_event.is_set():
            try:
                r, _, _ = select.select([self.fd], [], [], 0.1)
                if not r:
                    continue
                data = os.read(self.fd, 1)
                if not data:
                    continue
                key = self._parse(data)
                if key:
                    self.q.put(key)
            except OSError:
                break

    def _parse(self, first: bytes) -> str | None:
        """1バイト（またはESCシーケンス）をキー名へ変換する。"""
        if first == b"\x1b":
            # 矢印キーは ESC [ A 〜 D、または ESC O A 〜 D の3バイト
            try:
                r, _, _ = select.select([self.fd], [], [], 0.05)
                if not r:
                    return "esc"
                second = os.read(self.fd, 1)
                if second not in (b"[", b"O"):
                    return None  # その他のシーケンスは無視
                r2, _, _ = select.select([self.fd], [], [], 0.05)
                if not r2:
                    return None
                third = os.read(self.fd, 1)
                return _ARROW_KEYS.get(third)
            except OSError:
                return "esc"
        return _SIMPLE_KEYS.get(first)