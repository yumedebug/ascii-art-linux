"""コマンドラインインターフェース。"""

import argparse
import os
import sys

from . import __version__
from .cache import Cache
from .config import Config, MODES, PRESETS, QUALITIES, apply_preset
from .utils import AppError, human_size


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ascii-player",
        description="ターミナルで動画をASCII / Unicode文字（+ANSIカラー）として再生するCLI動画プレイヤー",
        epilog=(
            "操作キー: Space=一時停止  q/Esc=終了  ←/→=±5秒シーク  ↑/↓=速度変更  "
            "+/-=明るさ  m=モード切替  c=カラー切替  r=速度リセット"
        ),
    )
    p.add_argument("input", nargs="?", help="YouTube URL またはローカル動画ファイル")
    p.add_argument("--mode", choices=MODES, help=f"レンダリングモード (default: ascii)")
    p.add_argument("--color", action="store_true", dest="force_color", help="カラー表示を強制する")
    p.add_argument("--no-color", action="store_true", dest="no_color", help="モノクロ表示にする")
    p.add_argument("--quality", choices=QUALITIES, help=f"YouTubeの画質 (default: 480)")
    p.add_argument("--preset", choices=PRESETS, default="normal", help="性能プリセット (default: normal)")
    p.add_argument("--width", type=int, help="表示幅の上限（文字セル数。端末より大きくても端末に収まる）")
    p.add_argument("--height", type=int, help="表示高さの上限（文字行数。端末より大きくても端末に収まる）")
    p.add_argument(
        "--cell-ratio",
        type=float,
        help="文字セルの 高さ/幅 比（default: 端末から自動判定。失敗時は 2.0）",
    )
    p.add_argument("--fps", type=float, help="再生FPS（default: 動画のFPS）")
    p.add_argument("--brightness", type=int, help="明るさ -100〜100 (default: 0)")
    p.add_argument("--contrast", type=float, help="コントラスト (default: 1.0)")
    p.add_argument("--speed", type=float, help="再生速度 (default: 1.0)")
    p.add_argument("--loop", action="store_true", help="終了後は先頭からループ再生する")
    p.add_argument("--no-audio", action="store_true", help="音声を再生しない")
    p.add_argument("--no-hud", action="store_true", help="HUD（ステータス表示）を出さない")
    p.add_argument("--frames", type=int, help="Nフレーム描画したら終了する（テスト・ベンチマーク用）")
    p.add_argument("--cache-list", action="store_true", help="キャッシュの一覧を表示する")
    p.add_argument("--cache-clear", action="store_true", help="キャッシュを全て削除する")
    p.add_argument("--cache-size", action="store_true", help="キャッシュの容量を表示する")
    p.add_argument("--debug", action="store_true", help="デバッグ情報を出力する")
    p.add_argument("--version", action="version", version=f"ascii-player {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cache_list or args.cache_clear or args.cache_size:
            return _handle_cache(args)
        if not args.input:
            print("エラー: 再生する動画（YouTube URL またはファイルパス）を指定してください。", file=sys.stderr)
            print("  ascii-player --help で使い方を確認できます。", file=sys.stderr)
            return 2
        if sys.version_info < (3, 11):
            print(
                f"エラー: Python 3.11以上が必要です（現在: {sys.version_info.major}.{sys.version_info.minor}）。",
                file=sys.stderr,
            )
            return 1

        cfg = Config(input=args.input, preset=args.preset)
        apply_preset(cfg)
        # 明示指定があればプリセットの上に重ねる
        if args.mode:
            cfg.mode = args.mode
        if args.quality:
            cfg.quality = args.quality
        if args.width is not None:
            cfg.width = args.width
        if args.height is not None:
            cfg.height = args.height
        if args.cell_ratio is not None:
            cfg.cell_ratio = args.cell_ratio
        if args.fps is not None:
            cfg.fps = args.fps
        if args.brightness is not None:
            cfg.brightness = args.brightness
        if args.contrast is not None:
            cfg.contrast = args.contrast
        if args.speed is not None:
            cfg.speed = args.speed
        cfg.force_color = args.force_color
        cfg.no_color = args.no_color
        cfg.loop = args.loop
        cfg.no_audio = args.no_audio
        cfg.no_hud = args.no_hud
        cfg.frames = args.frames
        cfg.debug = args.debug

        if cfg.debug:
            print(
                f"[debug] mode={cfg.mode} preset={cfg.preset} quality={cfg.quality} "
                f"fps={cfg.fps} speed={cfg.speed} cell_ratio={cfg.cell_ratio or 'auto'} "
                f"color={'off' if cfg.no_color else 'auto'}",
                file=sys.stderr,
            )

        from .player import Player

        Player(cfg).run()
        return 0
    except AppError as e:
        print(f"エラー: {e}", file=sys.stderr)
        if e.hint:
            print(f"  対処: {e.hint}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0


def _handle_cache(args: argparse.Namespace) -> int:
    cache = Cache()
    if args.cache_list:
        entries = cache.list_entries()
        if not entries:
            print("(キャッシュは空です)")
            return 0
        for key, entry in entries:
            size = 0
            try:
                size = os.path.getsize(entry["path"])
            except OSError:
                pass
            print(f"{key}  {entry.get('quality', '-'):>4}  {human_size(size):>8}  {entry.get('title', '')[:40]}")
        return 0
    if args.cache_size:
        count, total = cache.total_size()
        print(f"キャッシュ: {count} ファイル / {human_size(total)}  ({cache.dir})")
        return 0
    if args.cache_clear:
        removed = cache.clear()
        print(f"キャッシュを削除しました（{removed} ファイル）。")
        return 0
    return 0