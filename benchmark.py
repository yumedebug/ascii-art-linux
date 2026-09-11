#!/usr/bin/env python3
"""ASCII Player ベンチマーク。

CPU使用率・RAM使用量・入力FPS・実際の描画FPS・ドロップフレーム数・
平均フレーム変換時間・端末解像度・動画解像度を測定して表示する。

使い方:
    python benchmarks/benchmark.py video.mp4 [--frames 300] [--mode halfblock]
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ascii_player import terminal as term  # noqa: E402
from ascii_player.decoder import VideoDecoder, probe_video  # noqa: E402
from ascii_player.renderer import Renderer, compute_pixel_dims  # noqa: E402
from ascii_player.timing import FrameScheduler  # noqa: E402


def read_cpu_times() -> tuple[int, int]:
    """/proc/self/stat から utime+stime (jiffies) を読む。"""
    try:
        with open("/proc/self/stat") as f:
            parts = f.read().split()
        # comm に空白が含まれる場合を考慮
        idx = parts.index(")") + 1
        utime = int(parts[idx + 11])
        stime = int(parts[idx + 12])
        return utime, stime
    except (OSError, ValueError, IndexError):
        return 0, 0


def read_rss_kb() -> int:
    """/proc/self/status の VmRSS (KB) を読む。"""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def clk_tck() -> float:
    try:
        return float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
    except (ValueError, KeyError):
        return 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description="ASCII Player ベンチマーク")
    parser.add_argument("video", help="動画ファイルパス")
    parser.add_argument("--frames", type=int, default=300, help="測定フレーム数 (default: 300)")
    parser.add_argument("--mode", choices=("ascii", "blocks", "halfblock"), default="halfblock")
    parser.add_argument("--no-color", action="store_true", help="モノクロで測定")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        print(f"エラー: ファイルが見つかりません: {args.video}", file=sys.stderr)
        return 1

    info = probe_video(args.video)
    cols, rows = term.get_terminal_size()
    color = "mono" if args.no_color else term.detect_color_mode()
    pw, ph, lines = compute_pixel_dims(cols, rows, args.mode, cell_ratio=term.detect_cell_ratio())
    fps = info["fps"]
    sched = FrameScheduler(fps)

    decoder = VideoDecoder(args.video, 0.0, pw, ph, fps)
    renderer = Renderer(args.mode, color)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)  # 描画時間の計測は/dev/nullへのwriteで行う

    print("ASCII Player Benchmark")
    print("-" * 22)

    start = time.monotonic()
    cpu0 = read_cpu_times()
    t0 = time.monotonic()

    rendered = 0
    dropped = 0
    frame_index = 0
    convert_times: list[float] = []
    render_times: list[float] = []

    while rendered < args.frames:
        data = decoder.read_frame(timeout=0.5)
        if data is None:
            continue
        if data == b"":
            break
        ft = sched.frame_time(frame_index, 0.0)
        now = time.monotonic() - t0
        if sched.should_drop(ft, now):
            dropped += 1
            frame_index += 1
            continue
        c0 = time.monotonic()
        frame = renderer.render(data, pw, ph)
        c1 = time.monotonic()
        convert_times.append((c1 - c0) * 1000)
        # 描画（write）の計測
        w0 = time.monotonic()
        os.write(devnull_fd, (term.ANSI.HOME + frame + "\n").encode())
        w1 = time.monotonic()
        render_times.append((w1 - w0) * 1000)
        rendered += 1
        frame_index += 1

    elapsed = time.monotonic() - start
    cpu1 = read_cpu_times()
    decoder.close()

    # CPU使用率（プロセス全体・平均）
    jiffies = (cpu1[0] - cpu0[0]) + (cpu1[1] - cpu0[1])
    tck = clk_tck()
    cpu_pct = (jiffies / tck) / elapsed * 100.0 if elapsed > 0 else 0.0
    ram_mb = read_rss_kb() / 1024.0

    avg_convert = sum(convert_times) / len(convert_times) if convert_times else 0.0
    avg_render = sum(render_times) / len(render_times) if render_times else 0.0
    render_fps = rendered / elapsed if elapsed > 0 else 0.0

    print(f"Input FPS:        {fps:.1f}")
    print(f"Render FPS:       {render_fps:.1f}")
    print(f"Dropped Frames:   {dropped}")
    print(f"Avg Convert Time: {avg_convert:.2f} ms")
    print(f"Avg Draw Time:    {avg_render:.2f} ms")
    print(f"CPU:              {cpu_pct:.0f}%")
    print(f"RAM:              {ram_mb:.0f} MB")
    print(f"Terminal:         {cols}x{rows}")
    print(f"Video:            {info['width']}x{info['height']} @ {fps:.1f}fps, {info['duration']:.1f}s")
    print(f"Pixel Buffer:     {pw}x{ph}")
    print(f"Mode:             {args.mode}")
    print(f"Color:            {color}")
    return 0


if __name__ == "__main__":
    sys.exit(main())