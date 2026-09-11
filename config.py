"""設定値の定義とプリセット。"""

from dataclasses import dataclass, field
from typing import Optional

MODES = ("ascii", "blocks", "halfblock")
QUALITIES = ("360", "480", "720", "1080", "best")
PRESETS = ("low", "normal", "quality")
COLOR_MODES = ("truecolor", "256", "basic", "mono")


@dataclass
class Config:
    # --- 入力 ---
    input: str = ""          # YouTube URL またはローカルファイルパス
    path: str = ""           # 解決後のローカルファイルパス

    # --- 表示 ---
    mode: str = "ascii"  # ascii | blocks | halfblock（デフォルトはASCIIアート）
    force_color: bool = False
    no_color: bool = False
    color: str = "auto"      # 実行時に detect_color_mode() で解決される
    width: Optional[int] = None
    height: Optional[int] = None

    # --- 動画 ---
    quality: str = "480"     # YouTube画質
    preset: str = "normal"   # low | normal | quality
    fps: Optional[float] = None
    brightness: int = 0
    contrast: float = 1.0
    speed: float = 1.0
    loop: bool = False
    no_audio: bool = False
    no_hud: bool = False
    debug: bool = False
    frames: Optional[int] = None  # テスト/ベンチマーク用: 描画フレーム数で停止

    # --- 内部設定 ---
    # 端末文字セルの 高さ/幅 比（アスペクト補正用）。
    # None なら端末から自動判定し、取れなければ DEFAULT_CELL_RATIO を使う。
    cell_ratio: Optional[float] = None
    max_cols: Optional[int] = None  # プリセットによる上限
    max_rows: Optional[int] = None
    max_fps: Optional[float] = None


def apply_preset(cfg: Config) -> Config:
    """プリセットに応じたデフォルト設定を適用する。

    明示的なCLI指定は cli.py 側でこの後に上書きされる。
    """
    if cfg.preset == "low":
        # 低スペックPC向け: 軽量なASCII変換・低解像度・30FPS上限
        cfg.mode = "ascii"
        cfg.max_cols = 84
        cfg.max_rows = 26
        cfg.max_fps = 30.0
    elif cfg.preset == "normal":
        # 標準: ASCIIアート（--mode halfblock で高密度表示に切替可能）
        cfg.mode = "ascii"
        cfg.max_fps = 60.0
    elif cfg.preset == "quality":
        # 高品質描画: 端末サイズいっぱいに halfblock + TrueColor
        cfg.mode = "halfblock"
        cfg.max_fps = 60.0
    return cfg