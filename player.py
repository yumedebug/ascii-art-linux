"""メインの再生ループ。

デコード・音声同期・フレームドロップ・キーボード操作・終了処理を統合する。

同期方針:
- マスタークロック = MediaClock（音声再生中は実時間で進む音声位置と一致）
- フレームは表示時刻より1フレーム以上遅れたら描画せず捨てる
- シーク・リサイズ・モード変更時はFFmpegパイプラインを再起動して同期を取り直す
"""

import os
import queue
import signal
import sys
import time

from . import terminal as term
from .audio import AudioPlayer
from .cache import Cache
from .config import Config
from .controls import KEY_ACTIONS, KeyReader
from .decoder import VideoDecoder, probe_video
from .downloader import resolve_input
from .renderer import Renderer, compute_pixel_dims
from .timing import FrameScheduler, MediaClock
from .utils import AppError, clamp, find_tool, format_time

_SEEK_STEP = 5.0
_SPEED_STEP_UP = 1.25
_SPEED_STEP_DOWN = 0.8
_BRIGHTNESS_STEP = 5


class Player:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.quit_flag = False
        self.paused = False
        self.resize_pending = False

        # 統計
        self.dropped = 0
        self.rendered = 0
        self.render_fps_ema = 0.0

        # 再生状態
        self.frame_index = 0
        self.video_start = 0.0
        self.duration = 0.0
        self.fps = 30.0
        self.pw = 120
        self.ph = 66
        self.lines = 33
        # 文字セルの 高さ/幅 比。None 指定なら端末から実測する（_prepare で解決）。
        self.cell_ratio = cfg.cell_ratio or term.DEFAULT_CELL_RATIO

        self.speed = cfg.speed
        self.brightness = cfg.brightness
        self.contrast = cfg.contrast
        self.mode = cfg.mode
        self.color_mode = cfg.color

        self.path = ""
        self.video: VideoDecoder | None = None
        self.audio: AudioPlayer | None = None
        self.clock = MediaClock(rate=self.speed)
        self.scheduler: FrameScheduler | None = None
        self.renderer: Renderer | None = None

        self.screen = sys.stdout
        self.q: queue.Queue = queue.Queue()
        self.keyreader: KeyReader | None = None
        self.raw: term.RawTerminal | None = None
        self._last_frame: bytes | None = None
        self._audio_warned = False
        self._audio_check_at = 0.0
        self._cleanup_done = False
        self._alt_active = False  # 代替画面へ入ったか（エラー時の復元エスケープ抑制用）

    # ------------------------------------------------------------------
    # 起動
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._prepare()
            self._start_pipeline(0.0)
            self._loop()
        finally:
            self._cleanup()

    def _prepare(self) -> None:
        if not find_tool("ffmpeg"):
            raise AppError(
                "FFmpeg が見つかりません。",
                hint="sudo apt install ffmpeg / sudo dnf install ffmpeg / sudo pacman -S ffmpeg など。",
            )
        if not find_tool("ffprobe"):
            raise AppError(
                "FFprobe が見つかりません。",
                hint="FFmpeg パッケージに同梱されています。",
            )
        self.path = resolve_input(self.cfg.input, self.cfg, Cache())
        info = probe_video(self.path)
        self.duration = info["duration"] or 0.0
        if not info["has_audio"] and not self.cfg.no_audio:
            print("注意: 音声ストリームが見つかりません。映像のみ再生します。", file=sys.stderr)
            self.cfg.no_audio = True

        self._setup_terminal()
        # 端末がピクセルサイズを返すなら実際の文字セル比を使う（4:3を正確にする）
        self.cell_ratio = self.cfg.cell_ratio or term.detect_cell_ratio()
        self.color_mode = term.detect_color_mode(self.cfg.force_color, self.cfg.no_color)
        self.renderer = Renderer(self.mode, self.color_mode, self.brightness, self.contrast)

        native_fps = info["fps"] or 30.0
        self.fps = self.cfg.fps or native_fps
        if self.cfg.max_fps:
            self.fps = min(self.fps, self.cfg.max_fps)
        self.scheduler = FrameScheduler(self.fps)
        self._update_dims()
        if self.cfg.debug:
            cols, rows = term.get_terminal_size()
            print(
                f"[debug] terminal={cols}x{rows} cell_ratio={self.cell_ratio:.3f} "
                f"→ art={self.pw}x{self.lines}",
                file=sys.stderr,
            )

        if not self.cfg.no_audio and info["has_audio"]:
            self.audio = AudioPlayer(self.path, debug=self.cfg.debug)
            if not self.audio.available():
                print("注意: 音声再生デバイス（aplay/ffplay）が見つかりません。映像のみ再生します。", file=sys.stderr)
                self.audio = None

        try:
            signal.signal(signal.SIGWINCH, self._on_sigwinch)
        except Exception:
            pass

    def _setup_terminal(self) -> None:
        cols, rows = term.get_terminal_size()
        if cols < 10 or rows < 3:
            raise AppError(f"端末が小さすぎます（{cols}x{rows}）。ウィンドウを広げてから再実行してください。")
        self.screen.write(term.ANSI.ENTER_ALT + term.ANSI.HIDE_CURSOR + term.ANSI.CLEAR)
        self.screen.flush()
        self._alt_active = True
        self.raw = term.RawTerminal()
        self.raw.__enter__()
        self.keyreader = KeyReader(sys.stdin.fileno(), self.q, enabled=term.is_tty(sys.stdin))
        self.keyreader.start()

    def _update_dims(self) -> None:
        cols, rows = term.get_terminal_size()
        # 描画領域は動画の縦横比によらず常に4:3（横:縦）に固定される。
        self.pw, self.ph, self.lines = compute_pixel_dims(
            cols,
            rows,
            self.mode,
            cell_ratio=self.cell_ratio,
            max_cols=self.cfg.max_cols,
            max_rows=self.cfg.max_rows,
            width=self.cfg.width,
            height=self.cfg.height,
        )

    # ------------------------------------------------------------------
    # パイプライン制御
    # ------------------------------------------------------------------

    def _start_pipeline(self, pos: float) -> None:
        """映像・音声パイプラインを指定位置から再起動し、クロックを再同期する。"""
        self._stop_video()
        self.video_start = pos
        self.frame_index = 0
        self.video = VideoDecoder(
            self.path, pos, self.pw, self.ph, self.fps, debug=self.cfg.debug
        )
        if self.audio:
            self.audio.start(pos, self.speed)
            if self.paused:
                self.audio.pause()
        self.clock.seek(pos)
        try:
            self.screen.write(term.ANSI.CLEAR + term.ANSI.HOME)
            self.screen.flush()
        except Exception:
            pass

    def _stop_video(self) -> None:
        if self.video:
            self.video.close()
            self.video = None

    def _stop_audio(self) -> None:
        if self.audio:
            self.audio.stop()

    # ------------------------------------------------------------------
    # メインループ
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self.quit_flag:
            if self.cfg.frames and self.rendered >= self.cfg.frames:
                break
            self._drain_keys()
            self._check_audio()
            if self.resize_pending:
                self.resize_pending = False
                self._on_resize()
            if self.paused:
                time.sleep(0.03)
                continue

            if self.video is None:
                break
            data = self.video.read_frame()
            if data is None:
                time.sleep(0.002)
                continue
            if data == b"":
                self._on_eof()
                continue

            # --- 音声クロックと同期し、古いフレームはドロップ ---
            ft = self.scheduler.frame_time(self.frame_index, self.video_start)
            now = self.clock.now()
            if self.scheduler.should_drop(ft, now):
                self.dropped += 1
                self.frame_index += 1
                continue

            wait = ft - now
            while wait > 0.003 and not self.quit_flag:
                self._drain_keys()
                if self.paused or self.resize_pending:
                    break
                time.sleep(min(wait, 0.02))
                wait = ft - self.clock.now()
            if self.quit_flag or self.paused or self.resize_pending:
                continue

            self._draw(data)
            self.frame_index += 1

    def _draw(self, data: bytes, count: bool = True) -> None:
        t0 = time.monotonic()
        try:
            frame = self.renderer.render(data, self.pw, self.ph)
        except Exception as e:
            if self.cfg.debug:
                print(f"描画エラー: {e}", file=sys.stderr)
            self.quit_flag = True
            return
        self._last_frame = data

        cols, _ = term.get_terminal_size()
        parts = [line for line in frame.split("\n")]
        if not self.cfg.no_hud and parts:
            # HUDは最終行のASCIIアート行に重ねて表示する。
            # 描画領域が端末の全行を使う場合でも行を追加しないため、
            # スクロールや余白行が発生しない（行間0で全画面が埋まる）。
            parts[-1] = term.pad_line(self._hud(), cols)
        # raw mode では OPOST が無効なため \n がカーソルを桁0へ戻さない。
        # 1行が端末幅ちょうどの ASCII 行は \n だけで2行進んで見える（行間が空く）ので
        # 明示的に \r\n で改行する。
        out = term.ANSI.HOME + "\r\n".join(parts)
        self.screen.write(out)
        self.screen.flush()

        dt = time.monotonic() - t0
        if dt > 0:
            inst = 1.0 / dt
            self.render_fps_ema = inst if self.render_fps_ema == 0 else self.render_fps_ema * 0.9 + inst * 0.1
        if count:
            self.rendered += 1

    def _hud(self) -> str:
        status = "⏸" if self.paused else "▶"
        pos = clamp(self.clock.now(), 0.0, max(self.duration, 1.0))
        line = (
            f"{status} {format_time(pos)} / {format_time(self.duration)} "
            f"| {int(self.render_fps_ema)} FPS | {self.mode} | {self.speed:.1f}x"
        )
        if self.dropped:
            line += f" | drop {self.dropped}"
        if self.brightness:
            line += f" | br {self.brightness:+d}"
        return line

    # ------------------------------------------------------------------
    # キー操作
    # ------------------------------------------------------------------

    def _check_audio(self) -> None:
        """音声シンクがエラー終了していないか定期的に確認する。

        デバイスが開けない等で音が全く出ていない場合に気づけるよう、
        一度だけ警告して音声を無効化する（映像は続行する）。
        """
        audio = self.audio
        if audio is None or self._audio_warned:
            return
        now = time.monotonic()
        if now - self._audio_check_at < 0.5:
            return
        self._audio_check_at = now
        if not audio.failed():
            return
        self._audio_warned = True
        print(
            "注意: 音声を再生できません（音声デバイスを開けなかった可能性があります）。"
            "映像のみ続行します。\n"
            "  対処: `aplay -l` で再生デバイスを確認するか、`--no-audio` で映像だけ再生してください。",
            file=sys.stderr,
        )
        audio.stop()
        self.audio = None

    def _drain_keys(self) -> None:
        while True:
            try:
                ev = self.q.get_nowait()
            except queue.Empty:
                break
            action = KEY_ACTIONS.get(ev)
            if action:
                self._handle_action(action)

    def _handle_action(self, action: str) -> None:
        if action == "pause":
            self._toggle_pause()
        elif action == "quit":
            self.quit_flag = True
        elif action == "seek_back":
            self._seek(-_SEEK_STEP)
        elif action == "seek_fwd":
            self._seek(_SEEK_STEP)
        elif action == "speed_up":
            self._change_speed(_SPEED_STEP_UP)
        elif action == "speed_down":
            self._change_speed(_SPEED_STEP_DOWN)
        elif action == "brightness_up":
            self._set_brightness(self.brightness + _BRIGHTNESS_STEP)
        elif action == "brightness_down":
            self._set_brightness(self.brightness - _BRIGHTNESS_STEP)
        elif action == "cycle_mode":
            self._cycle_mode()
        elif action == "cycle_color":
            self._cycle_color()
        elif action == "reset_speed":
            self._change_speed_to(1.0)

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            self.clock.pause()
            if self.audio:
                self.audio.pause()
        else:
            self.clock.resume()
            if self.audio:
                self.audio.resume()
        if self._last_frame is not None:
            self._draw(self._last_frame, count=False)

    def _seek(self, delta: float) -> None:
        pos = clamp(self.clock.now() + delta, 0.0, self.duration)
        self._start_pipeline(pos)
        self._last_frame = None

    def _on_resize(self) -> None:
        self._update_dims()
        pos = self.clock.now()
        self._start_pipeline(pos)
        self._last_frame = None

    def _cycle_mode(self) -> None:
        order = ("ascii", "blocks", "halfblock")
        idx = order.index(self.mode)
        self.mode = order[(idx + 1) % len(order)]
        self.renderer.set_mode(self.mode)
        self._on_resize()

    def _cycle_color(self) -> None:
        supported = self._supported_color_modes()
        idx = supported.index(self.color_mode) if self.color_mode in supported else 0
        self.color_mode = supported[(idx + 1) % len(supported)]
        self.renderer.set_color(self.color_mode)
        if self._last_frame is not None:
            self._draw(self._last_frame, count=False)

    def _supported_color_modes(self) -> list[str]:
        modes: list[str] = []
        if self.cfg.no_color:
            return ["mono"]
        ct = os.environ.get("COLORTERM", "").lower()
        term_env = os.environ.get("TERM", "")
        if ct in ("truecolor", "24bit"):
            modes.append("truecolor")
        if "256color" in term_env:
            modes.append("256")
        if term_env and term_env != "dumb":
            modes.append("basic")
        if self.cfg.force_color:
            return modes or ["basic"]
        modes.append("mono")
        return modes or ["mono"]

    def _change_speed(self, factor: float) -> None:
        self._change_speed_to(clamp(self.speed * factor, 0.25, 4.0))

    def _change_speed_to(self, speed: float) -> None:
        self.speed = speed
        self.clock.set_rate(self.speed)
        if self.audio:
            self.audio.start(self.clock.now(), self.speed)
            if self.paused:
                self.audio.pause()

    def _set_brightness(self, value: int) -> None:
        self.brightness = clamp(int(value), -100, 100)
        self.renderer.set_brightness_contrast(self.brightness, self.contrast)
        if self._last_frame is not None:
            self._draw(self._last_frame, count=False)

    def _on_eof(self) -> None:
        if self.cfg.loop:
            self._start_pipeline(0.0)
            self._last_frame = None
        else:
            self.quit_flag = True

    def _on_sigwinch(self, *args) -> None:
        self.resize_pending = True

    # ------------------------------------------------------------------
    # 終了処理
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        if self._cleanup_done:
            return
        self._cleanup_done = True
        # 1. プロセス終了
        self._stop_video()
        self._stop_audio()
        # 2. キー監視スレッド停止
        if self.keyreader:
            self.keyreader.stop()
        # 3. 端末設定復元（raw mode → 通常、カーソル表示、カラーリセット、代替画面から復帰）
        if self.raw:
            self.raw.restore()
        if self._alt_active:
            try:
                self.screen.write(term.ANSI.RESET + term.ANSI.SHOW_CURSOR + term.ANSI.LEAVE_ALT)
                self.screen.flush()
            except Exception:
                pass