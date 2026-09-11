"""フレームバッファ（raw RGB）を文字+ANSI文字列へ変換する。

- ascii / blocks: 1セル = 1ピクセル
- halfblock: 1セル = 上下2ピクセル（前景=上、背景=下 の2色表現）
- numpy があれば輝度計算・文字選択・色量子化をまとめてベクトル化する
  （高密度（画面全体）のASCIIアートでも60FPSを維持するため。
   numpy なしの環境でも同じ絵になることを tests で保証している）
"""

from .converter import (
    HAS_NUMPY,
    CHAR_SETS,
    HALFBLOCK_CHAR,
    HALFBLOCK_CHARS,
    LUM_R,
    LUM_G,
    LUM_B,
    ColorMapper,
    apply_brightness_contrast,
    make_char_table,
    rgb_to_16_array,
    rgb_to_256_array,
)
from .utils import clamp

if HAS_NUMPY:
    import numpy as np


# 描画領域の縦横比（横:縦）は常に4:3に固定する
TARGET_ASPECT = 4.0 / 3.0

# 表示アスペクトの許容誤差（4:3 に対する相対値）。
# 文字セル数は整数なので丸め誤差が出る。誤差がこの範囲なら面積（＝密度）を、
# 超えるなら4:3の正確さを優先する。
ASPECT_TOLERANCE = 0.01


def compute_pixel_dims(
    cols: int,
    rows: int,
    mode: str,
    *,
    cell_ratio: float = 2.0,
    max_cols: int | None = None,
    max_rows: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> tuple[int, int, int]:
    """端末の文字セル数から、描画領域のピクセルサイズを計算する。

    描画領域の縦横比は動画によらず常に4:3（横:縦）に固定する。
    端末の文字は幅≠高さなので、文字セルの縦横比 (cell_ratio) で補正する。
    --width / --height を含め、指定値は「上限」として扱い、
    必ず端末の物理サイズ（cols × rows）に収める。はみ出すと端末が行を
    折り返してしまい、行間0・全画面表示が崩れるため。
    行数 r を大きい方から試し、4:3 の誤差が許容範囲（ASPECT_TOLERANCE）に
    収まる中で最大の (c, r) を選ぶ（＝ 端末が4:3より横長なら高さ基準、
    縦長なら幅基準になる）。許容範囲に入る組がなければ誤差最小の組を使う。
    動画はこの領域いっぱいに引き伸ばして描画される（例: 16:9動画は
    高さを維持したまま横方向のみ圧縮されて4:3になる）。
    戻り値: (ピクセル幅, ピクセル高さ, 文字行数)
    """
    limit_cols = max(1, cols)
    limit_rows = max(1, rows)
    if max_cols:
        limit_cols = min(limit_cols, max_cols)
    if max_rows:
        limit_rows = min(limit_rows, max_rows)
    if width:
        limit_cols = min(limit_cols, width)
    if height:
        limit_rows = min(limit_rows, height)

    # 表示アスペクト = c / (r * cell_ratio)。これが 4:3 になる幅 c を選ぶ。
    # r を大きい順に試し、誤差が許容範囲内で最大の領域を取る。
    chosen = None
    fallback = None
    for candidate_r in range(limit_rows, 0, -1):
        candidate_c = round(candidate_r * cell_ratio * TARGET_ASPECT)
        if not 1 <= candidate_c <= limit_cols:
            continue
        error = abs(candidate_c / (candidate_r * cell_ratio) - TARGET_ASPECT) / TARGET_ASPECT
        if fallback is None or error < fallback[0]:
            fallback = (error, candidate_c, candidate_r)
        if error <= ASPECT_TOLERANCE:
            chosen = (candidate_c, candidate_r)
            break
    if chosen is not None:
        c, r = chosen
    elif fallback is not None:
        c, r = fallback[1], fallback[2]
    else:
        c, r = limit_cols, 1  # 極端に狭い端末向けのフォールバック
    ph = r * 2 if mode == "halfblock" else r
    return c, ph, r


class Renderer:
    """フレームバッファを1フレーム分の文字列へ変換する。"""

    def __init__(
        self,
        mode: str = "halfblock",
        color: str = "truecolor",
        brightness: int = 0,
        contrast: float = 1.0,
    ) -> None:
        self.mode = mode
        self.brightness = brightness
        self.contrast = contrast
        self.color_mapper = ColorMapper(color)
        self._tables: dict[str, list[str]] = {}

    # ---------- 設定変更 ----------

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def set_color(self, mode: str) -> None:
        self.color_mapper.set_mode(mode)

    def set_brightness_contrast(self, brightness: int, contrast: float) -> None:
        self.brightness = int(brightness)
        self.contrast = float(contrast)

    def _char_table(self) -> list[str]:
        """ascii/blocks 用の輝度→文字テーブル（brightness/contrast適用済み）。"""
        key = (self.mode, self.brightness, self.contrast)
        table = self._tables.get(key)
        if table is None:
            raw = make_char_table(CHAR_SETS[self.mode])
            table = [
                raw[int(apply_brightness_contrast(l, self.brightness, self.contrast))]
                for l in range(256)
            ]
            self._tables[key] = table
        return table

    def _bc(self, v: float) -> int:
        return int(apply_brightness_contrast(v, self.brightness, self.contrast))

    def _adjust_rgb(self, arr):
        """brightness/contrast をフレーム全体へまとめて適用する。

        スカラー実装 (apply_brightness_contrast + int()) と1画素ずつ同じ値に
        なるよう float64 で計算し、クリップ後に切り捨てる。
        未指定なら入力配列をそのまま返す。
        """
        if not self.brightness and self.contrast == 1.0:
            return arr
        adj = (arr.astype(np.float64) - 128.0) * self.contrast + 128.0 + self.brightness
        return np.clip(adj, 0.0, 255.0).astype(np.uint8)

    @staticmethod
    def _luma_raw(rgb):
        """RGB配列 → 輝度（float64、丸めなし）。

        スカラー実装と同じ加算順で計算する。
        """
        return rgb[..., 0] * LUM_R + rgb[..., 1] * LUM_G + rgb[..., 2] * LUM_B

    def _luma(self, rgb):
        """RGB配列（整数値）→ 輝度(0-255, uint8)。

        スカラー実装の round(LUM_R*r + LUM_G*g + LUM_B*b) と同じ最近接丸め。
        """
        return np.rint(self._luma_raw(rgb)).astype(np.uint8)

    def _adjust_luma(self, luma):
        """輝度配列（float）へ brightness/contrast を適用して uint8 にする。

        mono は輝度の段階で適用する（スカラー実装と同じ）。
        """
        if not self.brightness and self.contrast == 1.0:
            return luma.astype(np.uint8)
        adj = (luma - 128.0) * self.contrast + 128.0 + self.brightness
        return np.clip(adj, 0.0, 255.0).astype(np.uint8)

    def _char_grid(self, luma):
        """輝度配列 → 文字配列。

        文字セットがASCIIのみ（ascii）なら uint8 のまま扱って高速化し、
        非ASCIIを含む場合（blocks の █▓▒░ など）は Unicode 配列にする。
        """
        table = self._char_table()
        try:
            packed = np.frombuffer("".join(table).encode("ascii"), np.uint8)
        except UnicodeEncodeError:
            return np.array(table, dtype="<U1")[luma]
        return packed[luma]

    @staticmethod
    def _rows_to_text(chars) -> list[str]:
        """文字配列を行ごとの文字列にする。"""
        if chars.dtype.kind == "U":
            return ["".join(row.tolist()) for row in chars]
        return [row.tobytes().decode("ascii") for row in chars]

    def _color_keys(self, rgb):
        """セルごとの色キー配列（キャッシュ引き用の整数）を作る。"""
        if self.color_mapper.mode == "truecolor":
            r = rgb[..., 0].astype(np.int32)
            g = rgb[..., 1].astype(np.int32)
            b = rgb[..., 2].astype(np.int32)
            return (r << 16) | (g << 8) | b
        if self.color_mapper.mode == "256":
            return rgb_to_256_array(rgb)
        return rgb_to_16_array(rgb)

    # ---------- 描画 ----------

    def render(self, buf: bytes, pw: int, ph: int) -> str:
        """raw RGB24 フレームを文字フレーム文字列へ変換する。"""
        if self.mode == "halfblock":
            return "\n".join(self._render_halfblock(buf, pw, ph))
        return "\n".join(self._render_grid(buf, pw, ph))

    def _render_grid(self, buf: bytes, pw: int, ph: int) -> list[str]:
        """ascii / blocks: 1セル = 1ピクセル。

        numpy がある場合は、輝度計算・文字選択・色量子化までを配列で行い、
        1文字ずつPythonループで計算しない（高密度描画でも60FPSを維持する）。
        """
        table = self._char_table()
        mode = self.color_mapper.mode
        mono = mode == "mono"
        lines: list[str] = []

        if HAS_NUMPY:
            arr = np.frombuffer(buf, np.uint8).reshape(ph, pw, 3)
            if mono:
                # monoは輝度から直接文字を選ぶので、輝度の段階で
                # brightness/contrast を適用する（numpyなし実装と同一の結果）。
                return self._rows_to_text(
                    self._char_grid(self._adjust_luma(self._luma_raw(arr)))
                )

            rgb = self._adjust_rgb(arr)
            texts = self._rows_to_text(self._char_grid(self._luma(rgb)))
            cm = self.color_mapper
            keys = self._color_keys(rgb)
            get_code = cm.fg_packed if mode == "truecolor" else cm.fg_index
            return [
                "".join([get_code(k) + ch for k, ch in zip(key_row.tolist(), text)])
                for key_row, text in zip(keys, texts)
            ]

        cm = self.color_mapper
        for y in range(ph):
            base = y * pw * 3
            row: list[str] = []
            if mono:
                for x in range(pw):
                    o = base + x * 3
                    l = self._bc(LUM_R * buf[o] + LUM_G * buf[o + 1] + LUM_B * buf[o + 2])
                    row.append(table[l])
            else:
                for x in range(pw):
                    o = base + x * 3
                    r = self._bc(buf[o])
                    g = self._bc(buf[o + 1])
                    b = self._bc(buf[o + 2])
                    l = int(round(LUM_R * r + LUM_G * g + LUM_B * b))
                    row.append(cm.fg(r, g, b) + table[l])
            lines.append("".join(row))
        return lines

    def _render_halfblock(self, buf: bytes, pw: int, ph: int) -> list[str]:
        """halfblock: 1セル = 上下2ピクセル。前景=上、背景=下。"""
        nlines = ph // 2
        mode = self.color_mapper.mode
        mono = mode == "mono"
        lines: list[str] = []

        if HAS_NUMPY:
            arr = np.frombuffer(buf, np.uint8).reshape(ph, pw, 3)
            rgb = self._adjust_rgb(arr)
            if mono:
                luma = self._luma(rgb)
                top = luma[0::2] > 128
                bot = luma[1::2] > 128
                idx = top.astype(np.uint8) * 2 + bot.astype(np.uint8)
                # HALFBLOCK_CHARS は非ASCII（▄▀█）なので1文字ずつ結合する
                return ["".join(HALFBLOCK_CHARS[i] for i in row.tolist()) for row in idx]

            cm = self.color_mapper
            keys = self._color_keys(rgb)
            top_keys = keys[0::2]
            bot_keys = keys[1::2]
            if mode == "truecolor":
                fg, bg = cm.fg_packed, cm.bg_packed
            else:
                fg, bg = cm.fg_index, cm.bg_index
            return [
                "".join(
                    [fg(t) + bg(b) + HALFBLOCK_CHAR for t, b in zip(tr.tolist(), br.tolist())]
                )
                for tr, br in zip(top_keys, bot_keys)
            ]

        cm = self.color_mapper
        for y in range(nlines):
            base_t = y * 2 * pw * 3
            base_b = base_t + pw * 3
            row: list[str] = []
            for x in range(pw):
                o1 = base_t + x * 3
                o2 = base_b + x * 3
                r1 = self._bc(buf[o1])
                g1 = self._bc(buf[o1 + 1])
                b1 = self._bc(buf[o1 + 2])
                r2 = self._bc(buf[o2])
                g2 = self._bc(buf[o2 + 1])
                b2 = self._bc(buf[o2 + 2])
                if mono:
                    l1 = int(round(LUM_R * r1 + LUM_G * g1 + LUM_B * b1))
                    l2 = int(round(LUM_R * r2 + LUM_G * g2 + LUM_B * b2))
                    row.append(
                        HALFBLOCK_CHARS[
                            (2 if l1 > 128 else 0) | (1 if l2 > 128 else 0)
                        ]
                    )
                else:
                    row.append(cm.fg(r1, g1, b1) + cm.bg(r2, g2, b2) + HALFBLOCK_CHAR)
            lines.append("".join(row))
        return lines