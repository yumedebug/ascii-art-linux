# ascii-player

**ターミナルで動画をASCII / Unicode文字として再生する Linux 向け CLI 動画プレイヤー**

*適当にファイルアップロードしたからわからんけどリリースから入れて使ってください*

YouTube またはローカルの動画ファイルを、ターミナル上で**文字だけ**で構成された
カラー映像として再生します。映像は必ず文字（+ ANSI カラーコード）によって描画され、
元の動画フレーム画像をターミナルへ直接表示することはありません。

```text
YouTube URL
    ↓ yt-dlp
動画をローカルへダウンロード
    ↓ FFmpeg
フレームをストリームでデコード（PNG等の一時画像は生成しない）
    ↓ 縮小 + 輝度/色解析
ASCII / Unicode文字へ変換
    ↓ ANSI TrueColor
文字に色を付けてターミナルへ描画
    ↓ 音声と同期
再生
```

## 特徴

- **文字だけの映像**: ASCII / Blocks / HalfBlock の3つのレンダリングモード
- **4:3固定の描画領域**: 動画の縦横比によらず描画領域は常に横:縦 = 4:3。16:9動画は高さを維持したまま横方向のみ圧縮して表示
- **高密度ASCIIアート**: `@%#*+=-:. ` を輝度に応じて細かく切り替え、文字を隙間なく連続配置（行間0）
- **TrueColor対応**: 24-bit RGB を各文字に適用（256色・基本16色・モノクロにもフォールバック）
- **音声同期**: 音声クロック基準。処理が追いつかない場合は**フレームドロップ**で同期を維持
- **キーボード操作**: 一時停止・シーク・速度変更・明るさ調整・モード切替
- **YouTube対応**: yt-dlp でダウンロードしてから再生（キャッシュで再ダウンロードを回避）
- **低スペック最適化**: FFmpeg側で縮小、NumPyで輝度・文字選択・色量子化をベクトル化、フレームは1枚ずつ処理
- **リサイズ追従**: 端末のサイズ変更に自動追従

## 必要環境

| 項目 | 要件 |
|---|---|
| OS | Linux（Ubuntu/Debian, Fedora, Arch, Raspberry Pi OS など） |
| Python | 3.11 以上 |
| FFmpeg / FFprobe | 動画デコード・音声再生に必須 |
| yt-dlp | YouTube再生に必須 |
| NumPy | 推奨（なくても動作するが、ベクトル化で高速化される） |

## インストール

### 1. FFmpeg のインストール

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch
sudo pacman -S ffmpeg
```

### 2. yt-dlp / NumPy のインストール

```bash
pip install yt-dlp numpy
```

### 3. プロジェクトのインストール

```bash
cd ascii-player
pip install -e .
```

これで `ascii-player` コマンドが使えるようになります。

## 起動方法

インストール不要ですぐ試す場合（プロジェクトルート `ascii-player/` で実行）:

```bash
python3 main.py "https://www.youtube.com/watch?v=VIDEO_ID"
python3 main.py video.mp4
```

その他の起動方法:

```bash
python3 -m ascii_player video.mp4          # モジュールとして実行
python3 ascii_player/__main__.py video.mp4  # スクリプトとして直接実行
.venv/bin/ascii-player video.mp4           # venv内コマンド
ascii-player video.mp4                     # pip install -e . 後（PATHに .venv/bin が必要）
```

> `ascii-player` コマンドが「見つからない」場合は、venvを有効化するかPATHを通してください:
>
> ```bash
> source .venv/bin/activate          # 一時的に有効化
> # または
> export PATH="$HOME/ascii-player/.venv/bin:$PATH"   # 常時（~/.bashrc に追記）
> ```

## 使い方

### YouTube を再生

```bash
ascii-player "https://www.youtube.com/watch?v=VIDEO_ID"
```

初回は自動でダウンロードされ、`~/.cache/ascii-player/` にキャッシュされます。
2回目以降はキャッシュから即座に再生されます。

### ローカル動画を再生

```bash
ascii-player video.mp4
ascii-player /home/user/Videos/movie.mp4
```

### ヘルプ / バージョン

```bash
ascii-player --help
ascii-player --version
```

## CLIオプション

```
ascii-player INPUT

--mode ascii|blocks|halfblock   レンダリングモード（default: ascii）
--color                         カラー表示を強制
--no-color                      モノクロ表示
--quality 360|480|720|1080|best YouTubeの画質（default: 480）
--preset low|normal|quality     性能プリセット
--width WIDTH                   表示幅の上限（文字セル数。端末より大きくても端末に収まる）
--height HEIGHT                 表示高さの上限（文字行数。同上）
--cell-ratio RATIO              文字セルの 高さ/幅 比（default: 端末から自動判定。失敗時は 2.0）
--fps FPS                       再生FPS（default: 動画のFPS）
--brightness VALUE              明るさ -100〜100（default: 0）
--contrast VALUE                コントラスト（default: 1.0）
--speed SPEED                   再生速度（default: 1.0）
--loop                          ループ再生
--no-audio                      音声を再生しない
--no-hud                        HUDを表示しない
--cache-list                    キャッシュ一覧
--cache-clear                   キャッシュ削除
--cache-size                    キャッシュ容量
--debug                         デバッグ出力
--version / --help
```

例:

```bash
# 低スペックPC向け（360p・軽量ASCII）
ascii-player URL --quality 360 --preset low

# 高品質（halfblock + TrueColor + 720p）
ascii-player URL --quality 720 --preset quality

# ローカル動画をモノクロ・1.5倍速で
ascii-player movie.mp4 --no-color --speed 1.5
```

## キーボード操作

再生中に使えるキー:

| キー | 操作 |
|---|---|
| `Space` | 一時停止 / 再開 |
| `q` / `Esc` | 終了 |
| `←` / `→` | 5秒戻る / 5秒進む |
| `↑` / `↓` | 再生速度アップ / ダウン |
| `+` / `-` | 明るさアップ / ダウン |
| `m` | レンダリングモード切替（ascii → blocks → halfblock） |
| `c` | カラーモード切替 |
| `r` | 再生速度を1.0xへリセット |

## レンダリングモード

### ASCII（`--mode ascii`）

輝度を文字へマッピングするクラシックなモード:

```text
@%#*+=-:.
```

描画領域は動画の縦横比によらず常に **4:3（横:縦）** に固定されます。
端末が4:3より横長なら高さを基準に、縦長なら幅を基準に、4:3を保ったまま
端末に収まる最大サイズを選びます（文字セル数は整数なので、4:3からの
誤差が1%以内に収まる範囲で最も密になるサイズを選びます）。
`--width` / `--height` は上限として扱われ、端末のサイズを超えません
（超えると端末が行を折り返してしまい、行間0の表示が崩れるため）。
文字セルの 高さ/幅 比は端末がピクセルサイズを返す場合に自動実測し、
返さない場合は 2.0 とします（`--cell-ratio` で明示指定も可能）。
16:9動画は高さを維持したまま横方向のみ圧縮されて4:3の領域いっぱいに描画されます。
また、各行は1文字ずつ隙間なく連続配置され、行間も空けずに表示されます
（HUDは最下行に重ねて表示。`--no-hud` で完全に隠せます）。

### Blocks（`--mode blocks`）

ブロック文字による密度表現:

```text
█▓▒░
```

### HalfBlock（`--mode halfblock`）

Unicodeの `▀` を1文字で**上下2ピクセル**分表現する高密度モード。
前景色=上ピクセル、背景色=下ピクセル として2色を1文字に込めます。

## TrueColor

カラー対応端末では各文字に `\x1b[38;2;R;G;Bm` 形式の24-bit RGBを適用します。
`COLORTERM` / `TERM` / `NO_COLOR` 環境変数を検査し、自動で
**TrueColor → 256色 → 基本16色 → モノクロ** の順にフォールバックします。

## 低スペックPC向け設定

Celeron / 4GB RAM / Raspberry Pi / 古いIntel CPU などで動作させるための設定:

```bash
ascii-player URL --quality 360 --preset low --no-audio
```

`--preset low` は以下を行います:

- 軽量な ASCII モード
- 表示サイズを制限（最大84列×26行）
- FPS上限30
- 360p〜480p のダウンロード推奨

動画デコードは FFmpeg 側で端末サイズまで縮小してから行われるため、
1080p の動画でも必要なピクセル数だけ処理します。

## 音声と同期

- マスタークロックは**音声クロック**（再生位置）です
- 映像フレームは表示時刻より1フレーム以上遅れたら**描画せずに捨てます**
- そのためCPUが遅くてフレーム処理が追いつかなくても、映像が音声に対して
  どんどん遅れることはありません（滑らかさより同期を優先）

## キャッシュ

ダウンロードした動画は `~/.cache/ascii-player/` に保存され、2回目以降は再利用されます。

```bash
ascii-player --cache-list    # 一覧
ascii-player --cache-size    # 容量
ascii-player --cache-clear   # 全削除
```

```text
~/.cache/ascii-player/
├── VIDEO_ID.mp4
└── metadata.json
```

## トラブルシューティング

### FFmpeg が見つからない
`sudo apt install ffmpeg`（Ubuntu/Debian）、`sudo dnf install ffmpeg`（Fedora）、
`sudo pacman -S ffmpeg`（Arch）でインストールしてください。

### yt-dlp が見つからない
`pip install yt-dlp` でインストールしてください。

### YouTube の動画が取得できない
- 動画が削除・非公開になっていないか確認
- 年齢制限付き動画は取得できない場合があります
- ネットワーク接続を確認

### 音が出ない
- `aplay -l` で再生デバイスがあるか確認（デバイスが使用中・無効だと無音になります）
- アプリ側で音声シンクの異常終了を検知した場合は警告を表示して映像のみ続行します
- 一時的に映像だけ見たい場合は `--no-audio`

### 画面がちらつく / 遅い
- `--quality 360 --preset low` を試す
- `--no-audio` で映像のみ再生
- 端末サイズを小さくする

### 終了後にカーソルが消えたまま
`reset` コマンドで端末を復元できます。通常はアプリが自動で復元しますが、
強制終了された場合はこの手順で復旧してください。

## ベンチマーク

```bash
python benchmarks/benchmark.py video.mp4 --frames 300
```

```text
ASCII Player Benchmark
----------------------
Input FPS:        30
Render FPS:       27.4
Dropped Frames:   8
Avg Convert Time: 3.2 ms
Avg Draw Time:    1.8 ms
CPU:              72%
RAM:              180 MB
Terminal:         120x35
Video:            640x360 @ 30.0fps, 10.0s
Pixel Buffer:     120x66
Mode:             halfblock
Color:            TrueColor
```

## テスト

```bash
python -m unittest discover -s tests -t .
```

## ライセンス

MIT License（LICENSE 参照）
