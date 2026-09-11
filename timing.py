"""再生クロックとフレームスケジューリング。

- MediaClock: 音声/再生位置を表すマスタークロック（壁時計ベース、一時停止・速度変更対応）
- FrameScheduler: フレームの表示時刻計算とフレームドロップ判定
"""

import time


class MediaClock:
    """メディア再生位置（秒）を返すマスタークロック。

    壁時計から経過時間を求め、base + pause_accum + elapsed * rate を返す。
    音声が再生されている場合は aplay が実時間で再生するため、
    このクロックは音声位置とほぼ一致する。
    """

    def __init__(self, rate: float = 1.0) -> None:
        self.base = 0.0            # 再生位置の基準（シークで更新）
        self.rate = rate           # 再生速度（1.0 = 等速）
        self._t0 = time.monotonic()
        self._paused = False
        self._pause_start: float | None = None
        self._pause_accum = 0.0

    def now(self) -> float:
        """現在のメディア再生位置（秒）。"""
        if self._paused:
            return self.base + self._pause_accum
        return self.base + self._pause_accum + (time.monotonic() - self._t0) * self.rate

    def pause(self) -> None:
        if not self._paused:
            self._paused = True
            self._pause_start = time.monotonic()

    def resume(self) -> None:
        if self._paused and self._pause_start is not None:
            self._pause_accum += (time.monotonic() - self._pause_start) * self.rate
            self._paused = False
            self._pause_start = None
            self._t0 = time.monotonic()

    def seek(self, position: float) -> None:
        """指定位置へジャンプする（一時停止中でも安全）。"""
        self.base = max(0.0, position)
        self._pause_accum = 0.0
        self._t0 = time.monotonic()

    def set_rate(self, rate: float) -> None:
        self.rate = rate


class FrameScheduler:
    """フレーム表示時刻の計算とフレームドロップ判定。"""

    def __init__(self, fps: float) -> None:
        self.fps = max(1.0, fps)
        self.frame_dur = 1.0 / self.fps

    def frame_time(self, index: int, video_start: float) -> float:
        """フレームindexの表示時刻（秒）。"""
        return video_start + index * self.frame_dur

    def should_drop(self, frame_time: float, now: float) -> bool:
        """フレームが表示時刻より1フレーム以上遅れていればドロップする。

        音声との同期を優先し、古くなったフレームは描画せずに捨てる。
        """
        return now - frame_time > self.frame_dur

    def wait_time(self, frame_time: float, now: float) -> float:
        """このフレームを表示するまで待つべき時間（秒）。"""
        return max(0.0, frame_time - now)