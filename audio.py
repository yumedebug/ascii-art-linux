"""FFmpeg + ALSA(aplay) パイプによる音声再生。

ffmpeg がデコードした PCM を aplay の stdin へ直接渡す（Pythonを介さない）。
再生クロックは player 側の MediaClock（壁時計ベース）が基準となる。
シーク・速度変更はパイプラインを再起動して対応する。
"""

import os
import signal
import subprocess

from .utils import find_tool


def atempo_args(speed: float) -> list[str]:
    """再生速度に応じた atempo フィルタ引数リスト（0.5〜2.0 の範囲に分割）。"""
    if abs(speed - 1.0) < 1e-6:
        return []
    s = speed
    args: list[str] = []
    while s > 2.0:
        args.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        args.append("atempo=0.5")
        s /= 0.5
    args.append(f"atempo={s:.6f}")
    return args


def sink_command(sink_name: str, rate: int = 48000, channels: int = 2) -> list[str]:
    """音声シンク（aplay / ffplay）のコマンドを組み立てる。"""
    if sink_name == "aplay":
        # aplay の -f は ALSA のフォーマット名（"S16_LE"）が必要。
        # ffmpeg 形式の "s16le" を渡すと「不正な拡張フォーマット」で
        # 即座に終了し、無音になる。
        return [
            "aplay", "-q", "-t", "raw",
            "-c", str(channels), "-r", str(rate), "-f", "S16_LE",
        ]
    # ffplay は ffmpeg 形式（"s16le"）を受け付ける
    return [
        "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
        "-f", "s16le", "-ar", str(rate), "-ac", str(channels), "-i", "pipe:0",
    ]


class AudioPlayer:
    """音声パイプライン（ffmpeg → aplay/ffplay）を管理する。"""

    def __init__(self, path: str, rate: int = 48000, channels: int = 2, debug: bool = False) -> None:
        self.path = path
        self.rate = rate
        self.channels = channels
        self.debug = debug
        self.ffmpeg: subprocess.Popen | None = None
        self.sink: subprocess.Popen | None = None
        if find_tool("aplay"):
            self.sink_name = "aplay"
        elif find_tool("ffplay"):
            self.sink_name = "ffplay"
        else:
            self.sink_name = None

    def available(self) -> bool:
        return self.sink_name is not None

    def start(self, seek: float = 0.0, speed: float = 1.0) -> None:
        """音声パイプラインを (再)起動する。"""
        self.stop()
        if not self.sink_name:
            return
        af = atempo_args(speed)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-ss", f"{seek:.3f}",
            "-i", self.path,
            "-vn",
            "-ac", str(self.channels),
            "-ar", str(self.rate),
        ]
        if af:
            cmd += ["-af", ",".join(af)]
        cmd += ["-f", "s16le", "pipe:1"]
        ffmpeg_err = subprocess.PIPE if self.debug else subprocess.DEVNULL
        self.ffmpeg = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ffmpeg_err)
        sink_cmd = sink_command(self.sink_name, self.rate, self.channels)
        # ffmpeg の stdout をそのままシンクの stdin へ直結する
        self.sink = subprocess.Popen(
            sink_cmd,
            stdin=self.ffmpeg.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if self.ffmpeg.stdout:
            self.ffmpeg.stdout.close()  # 親プロセス側は閉じる（子が引き継ぐ）

    def pause(self) -> None:
        """音声パイプラインを一時停止する（SIGSTOP）。"""
        for p in (self.sink, self.ffmpeg):
            if p and p.poll() is None:
                try:
                    os.kill(p.pid, signal.SIGSTOP)
                except (OSError, ProcessLookupError):
                    pass

    def resume(self) -> None:
        """音声パイプラインを再開する（SIGCONT）。"""
        for p in (self.sink, self.ffmpeg):
            if p and p.poll() is None:
                try:
                    os.kill(p.pid, signal.SIGCONT)
                except (OSError, ProcessLookupError):
                    pass

    def is_alive(self) -> bool:
        return self.sink is not None and self.sink.poll() is None

    def failed(self) -> bool:
        """音声シンクがエラー終了したか（＝音が出ていない可能性が高い）。

        デバイスが使用中、サウンドカードが無い、フォーマット非対応などの
        場合はここで検知できる。正常終了（0）は失敗と見なさない。
        """
        if self.sink is None:
            return False
        rc = self.sink.poll()
        return rc is not None and rc != 0

    def stop(self) -> None:
        for p in (self.sink, self.ffmpeg):
            if p and p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        for p in (self.sink, self.ffmpeg):
            if p is None:
                continue
            try:
                p.wait(timeout=1)
            except Exception:
                try:
                    p.kill()
                    p.wait(timeout=1)
                except Exception:
                    pass
        self.sink = None
        self.ffmpeg = None