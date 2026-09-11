"""FFmpegパイプによるフレームストリームデコード。

動画をPNG等の大量の一時画像へ展開せず、FFmpegのrawvideo出力を
パイプで受け取り、Python側で1フレームずつ処理する。
リサイズはFFmpeg側（scaleフィルタ）で行い、無駄な高解像度デコードを避ける。
"""

import json
import os
import select
import subprocess

from .utils import AppError, find_tool


class VideoDecoder:
    """FFmpeg から raw RGB24 フレームをストリームで読み出す。"""

    def __init__(
        self,
        path: str,
        seek: float = 0.0,
        width: int = 120,
        height: int = 66,
        fps: float = 30.0,
        debug: bool = False,
    ) -> None:
        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg:
            raise AppError(
                "FFmpeg が見つかりません。",
                hint="sudo apt install ffmpeg / sudo dnf install ffmpeg などでインストールしてください。",
            )
        vf = f"scale={int(width)}:{int(height)}:flags=bilinear,fps={fps:.6f}"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-ss", f"{seek:.3f}",   # シーク（-i の前 = 高速キーフレームシーク）
            "-i", path,
            "-an",                  # 音声なし（音声は audio.py が別パイプラインで再生）
            "-vf", vf,
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "pipe:1",
        ]
        self.frame_size = int(width) * int(height) * 3
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if debug else subprocess.DEVNULL,
        )
        self._fd = self.proc.stdout.fileno()
        os.set_blocking(self._fd, False)  # 非ブロッキングで select と組み合わせる
        self._buf = bytearray()
        self._eof = False

    def _take_frame(self) -> bytes:
        """バッファから1フレーム分を取り出す。"""
        frame = bytes(self._buf[: self.frame_size])
        del self._buf[: self.frame_size]
        return frame

    def read_frame(self, timeout: float = 0.05) -> bytes | None:
        """1フレーム読み出す。

        戻り値:
          bytes  ... フレームデータ（width*height*3バイト）
          None   ... まだデータが到着していない（タイムアウト）
          b""    ... EOF（動画の終端）

        バッファに確定済みフレームがあれば、パイプを読む前にそれを返す。
        パイプのEOFを検出しても、バッファに残ったフレームを先に渡し切って
        から b"" を返す（そうしないと動画の終端が無言で切り捨てられ、
        再生が途中で止まったように見える）。
        """
        if len(self._buf) >= self.frame_size:
            return self._take_frame()
        if self._eof:
            return b""
        try:
            r, _, _ = select.select([self._fd], [], [], timeout)
        except (OSError, ValueError):
            return b""
        if not r:
            return None
        try:
            chunk = os.read(self._fd, 65536)
        except (BlockingIOError, InterruptedError):
            return None
        if chunk:
            self._buf.extend(chunk)
            if len(self._buf) >= self.frame_size:
                return self._take_frame()
            return None
        # 空読み = パイプのEOF。ここに来る時点でバッファに確定済みフレームは
        # 残っていない（あった場合は冒頭で返している）ので取りこぼしはない。
        self._eof = True
        return b""

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
        if self.proc.stdout:
            try:
                self.proc.stdout.close()
            except Exception:
                pass


def parse_fps(value: str | None) -> float | None:
    """ffprobe の FPS表現（"30000/1001" など）を float に変換する。"""
    if not value:
        return None
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            den = float(den)
            return float(num) / den if den else None
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def probe_video(path: str) -> dict:
    """ffprobe で動画のメタデータ（duration, fps, 音声有無, 解像度）を取得する。"""
    ffprobe = find_tool("ffprobe")
    if not ffprobe:
        raise AppError(
            "FFprobe が見つかりません。",
            hint="FFmpeg パッケージに同梱されています（sudo apt install ffmpeg など）。",
        )
    cmd = [ffprobe, "-v", "error", "-of", "json", "-show_format", "-show_streams", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AppError(
            "動画ファイルを開けません。ファイルが壊れている可能性があります。",
            hint=result.stderr.strip()[:200],
        )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not video:
        raise AppError("動画ストリームが見つかりません。", hint="動画ファイルを確認してください。")
    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    fps = parse_fps(video.get("avg_frame_rate")) or parse_fps(video.get("r_frame_rate")) or 30.0
    try:
        vw = int(video.get("width") or 0)
        vh = int(video.get("height") or 0)
    except (TypeError, ValueError):
        vw = vh = 0
    return {
        "duration": duration,
        "fps": fps,
        "has_audio": has_audio,
        "width": vw,
        "height": vh,
    }