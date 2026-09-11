"""フレーム→文字変換のコアロジック。

RGB→輝度変換、文字マッピング、brightness/contrast、ANSIカラー生成を担当する。
numpy があれば輝度計算・文字選択をベクトル化する（なければ純Pythonで動作）。
"""

from .utils import clamp

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:  # pragma: no cover - numpy なしでも動作するフォールバック
    np = None
    HAS_NUMPY = False

# Rec.709 係数: Y = 0.2126R + 0.7152G + 0.0722B
LUM_R, LUM_G, LUM_B = 0.2126, 0.7152, 0.0722
_LUM_VEC = (LUM_R, LUM_G, LUM_B)

# 文字セットは「明るい → 暗い」順
CHAR_SETS = {
    "ascii": "@%#*+=-:. ",
    "blocks": "█▓▒░ ",
}

# halfblock のモノクロフォールバック用ラダー:
#   インデックス = (上ピクセルが明るい ? 2 : 0) | (下ピクセルが明るい ? 1 : 0)
HALFBLOCK_CHARS = " ▄▀█"

# halfblock カラーモードで使う文字
HALFBLOCK_CHAR = "▀"

# 色→ANSIエスケープのキャッシュ上限。
# 映像は最大1600万通り以上の色を含むため、無制限に貯めると長時間の再生で
# メモリを食い尽くして途中で落ちる。上限を超えたら捨てて作り直す。
MAX_COLOR_CACHE = 1 << 16  # 65536 エントリ（≒数MB）


def _cache_put(cache: dict, key, value: str) -> None:
    """色キャッシュへ登録する。上限に達していたら一度捨てる（メモリ上限を守る）。"""
    if len(cache) >= MAX_COLOR_CACHE:
        cache.clear()
    cache[key] = value


def luminance(r: float, g: float, b: float) -> float:
    """RGB(0-255) → 輝度(0-255)。"""
    return LUM_R * r + LUM_G * g + LUM_B * b


def apply_brightness_contrast(value: float, brightness: int, contrast: float) -> float:
    """brightness（加算）と contrast（128を中心としたスケール）を適用する。"""
    return clamp((value - 128.0) * contrast + 128.0 + brightness, 0.0, 255.0)


def make_char_table(charset: str) -> list[str]:
    """輝度(0-255) → 文字 の変換テーブルを作る。"""
    n = len(charset)
    table = []
    for l in range(256):
        # 明るい(255) → 先頭文字、暗い(0) → 末尾文字
        idx = round((255 - l) * (n - 1) / 255)
        table.append(charset[idx])
    return table


def rgb_to_256(r: int, g: int, b: int) -> int:
    """RGB → xterm 256色インデックス。"""
    # グレースケール判定（RGBが近い場合）
    if abs(r - g) < 8 and abs(g - b) < 8:
        gray = round((r + g + b) / 3.0 / 255.0 * 23.0)
        return 232 + gray
    # 6x6x6 カラーキューブ
    def q(v: int) -> int:
        return 0 if v < 48 else 1 if v < 115 else 2 if v < 155 else 3 if v < 195 else 4 if v < 235 else 5

    return 16 + 36 * q(r) + 6 * q(g) + q(b)


def rgb_to_16(r: int, g: int, b: int) -> int:
    """RGB → ANSI基本16色インデックス（0-15）。"""
    bright = max(r, g, b) > 191
    rbit = 1 if r > 127 else 0
    gbit = 1 if g > 127 else 0
    bbit = 1 if b > 127 else 0
    base = (rbit << 2) | (gbit << 1) | bbit
    return base + (8 if bright else 0)


class ColorMapper:
    """カラーモードに応じたANSI前景/背景エスケープを生成する（キャッシュ付き）。

    ベクトル化パス（renderer.py）からは fg_packed / fg_index を使う。
    これらはエスケープ文字列を int キーで引けるため、1セルごとの
    タプル生成とメソッド呼び出しを避けられる。
    """

    def __init__(self, mode: str = "truecolor") -> None:
        self.mode = mode
        self._cache: dict[tuple, str] = {}
        self._packed_fg: dict[int, str] = {}
        self._packed_bg: dict[int, str] = {}
        self._index_fg: dict[int, str] = {}
        self._index_bg: dict[int, str] = {}

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._cache.clear()
        self._packed_fg.clear()
        self._packed_bg.clear()
        self._index_fg.clear()
        self._index_bg.clear()

    # --- ベクトル化パス用（1セルごとのタプル生成と呼び出しを避ける） ---

    def fg_packed(self, key: int) -> str:
        """0xRRGGBB → 前景エスケープ（truecolor用・キャッシュ付き）。"""
        if self.mode == "mono":
            return ""
        code = self._packed_fg.get(key)
        if code is None:
            code = self._fg_code((key >> 16) & 0xFF, (key >> 8) & 0xFF, key & 0xFF)
            _cache_put(self._packed_fg, key, code)
        return code

    def bg_packed(self, key: int) -> str:
        """0xRRGGBB → 背景エスケープ（truecolor用・キャッシュ付き）。"""
        if self.mode == "mono":
            return ""
        code = self._packed_bg.get(key)
        if code is None:
            code = self._bg_code((key >> 16) & 0xFF, (key >> 8) & 0xFF, key & 0xFF)
            _cache_put(self._packed_bg, key, code)
        return code

    def fg_index(self, index: int) -> str:
        """色番号（256色: 0-255 / 基本16色: 0-15）→ 前景エスケープ。

        ベクトル化パスでは色の量子化まで済ませた番号をここへ渡す。
        """
        if self.mode == "mono":
            return ""
        code = self._index_fg.get(index)
        if code is None:
            code = self._index_code(index, background=False)
            _cache_put(self._index_fg, index, code)
        return code

    def bg_index(self, index: int) -> str:
        """色番号（256色: 0-255 / 基本16色: 0-15）→ 背景エスケープ。"""
        if self.mode == "mono":
            return ""
        code = self._index_bg.get(index)
        if code is None:
            code = self._index_code(index, background=True)
            _cache_put(self._index_bg, index, code)
        return code

    def _index_code(self, index: int, background: bool) -> str:
        """量子化済みの色番号 → エスケープ（キャッシュミス時のみ呼ばれる）。"""
        if self.mode == "256":
            return f"\x1b[{'48' if background else '38'};5;{index}m"
        offset = 40 if background else 30
        bright_offset = 92 if background else 82
        return (
            f"\x1b[{offset + index}m"
            if index < 8
            else f"\x1b[{bright_offset + index}m"
        )

    def fg(self, r: int, g: int, b: int) -> str:
        if self.mode == "mono":
            return ""
        key = ("f", r, g, b)
        code = self._cache.get(key)
        if code is None:
            code = self._fg_code(r, g, b)
            _cache_put(self._cache, key, code)
        return code

    def bg(self, r: int, g: int, b: int) -> str:
        if self.mode == "mono":
            return ""
        key = ("b", r, g, b)
        code = self._cache.get(key)
        if code is None:
            code = self._bg_code(r, g, b)
            _cache_put(self._cache, key, code)
        return code

    def _fg_code(self, r: int, g: int, b: int) -> str:
        if self.mode == "truecolor":
            return f"\x1b[38;2;{r};{g};{b}m"
        if self.mode == "256":
            return f"\x1b[38;5;{rgb_to_256(r, g, b)}m"
        idx = rgb_to_16(r, g, b)
        return f"\x1b[{30 + idx}m" if idx < 8 else f"\x1b[{82 + idx}m"

    def _bg_code(self, r: int, g: int, b: int) -> str:
        if self.mode == "truecolor":
            return f"\x1b[48;2;{r};{g};{b}m"
        if self.mode == "256":
            return f"\x1b[48;5;{rgb_to_256(r, g, b)}m"
        idx = rgb_to_16(r, g, b)
        return f"\x1b[{40 + idx}m" if idx < 8 else f"\x1b[{92 + idx}m"


# ---------------------------------------------------------------------------
# ベクトル化版の色量子化（numpy がある場合のみ renderer から呼ばれる）
# スカラー版 rgb_to_256 / rgb_to_16 と同一の結果になることを tests で保証する。
# ---------------------------------------------------------------------------


def rgb_to_256_array(rgb):
    """(...,3) uint8 のRGB配列 → xterm 256色インデックス配列。"""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    # グレースケール判定（RGBが近い場合）
    gray = (np.abs(r - g) < 8) & (np.abs(g - b) < 8)
    gray_idx = np.rint((r + g + b) / 3.0 / 255.0 * 23.0).astype(np.int16) + 232

    def q(v):
        return np.select([v < 48, v < 115, v < 155, v < 195, v < 235], [0, 1, 2, 3, 4], 5)

    cube = 16 + 36 * q(r) + 6 * q(g) + q(b)
    return np.where(gray, gray_idx, cube).astype(np.int32)


def rgb_to_16_array(rgb):
    """(...,3) uint8 のRGB配列 → ANSI基本16色インデックス配列。"""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    bright = np.maximum(np.maximum(r, g), b) > 191
    base = (
        ((r > 127).astype(np.int16) << 2)
        | ((g > 127).astype(np.int16) << 1)
        | (b > 127).astype(np.int16)
    )
    return (base + np.where(bright, 8, 0)).astype(np.int32)


def halfblock_index(upper_luma: int, lower_luma: int, threshold: int = 128) -> int:
    """モノクロhalfblock用の文字インデックスを返す。"""
    return (2 if upper_luma > threshold else 0) | (1 if lower_luma > threshold else 0)