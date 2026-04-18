# yt-music

Download YouTube Music playlists, convert to mp3/aac/opus, and serve files to your phone.

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) (for audio conversion and metadata embedding)

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Commands

### List tracks in a playlist

Preview what's in a playlist without downloading anything.

```bash
yt-music list -p "https://music.youtube.com/playlist?list=PLxxxx"
```

### Download a playlist

```bash
# Download as mp3 (best quality, 320kbps)
yt-music download -p "https://music.youtube.com/playlist?list=PLxxxx"

# Download as aac with high quality (192kbps — perceptually equivalent to mp3 256kbps)
yt-music download -p "https://music.youtube.com/playlist?list=PLxxxx" -f aac -q high

# Faster with more parallel workers
yt-music download -p "https://music.youtube.com/playlist?list=PLxxxx" -w 10

# Custom output directory
yt-music download -p "https://music.youtube.com/playlist?list=PLxxxx" -o ~/Music/my-playlist
```

Re-running the same command will **skip already-downloaded tracks**.

### Convert existing files

Convert downloaded files to a different format. Automatically detects and skips lower-quality duplicates.

```bash
# Convert downloads to aac
yt-music convert -i ./downloads -f aac -q high -o ./downloads/aac

# Convert to opus (smallest files) with 8 parallel workers
yt-music convert -i ./downloads -f opus -q high -w 8

# Override with an explicit bitrate
yt-music convert -i ./downloads -f mp3 -b 192
```

### Serve files to your phone

Start a web server to browse, play, and download tracks from your phone's browser.

```bash
yt-music serve -i ./downloads/aac

# Custom port
yt-music serve -i ./downloads -p 9090
```

Open the displayed network URL (e.g. `http://192.168.1.x:8000`) on your phone. The page lets you:

- Stream tracks in the browser
- Download individual files
- Download everything as a ZIP

> **Note:** If you want files in the iOS Music app, use **aac** or **mp3** format. Opus files will play in Safari but won't import to Apple Music.

## Quality tiers

The `-q` option auto-selects perceptually equivalent bitrates for each codec:

| Quality  | MP3    | AAC    | Opus   |
|----------|--------|--------|--------|
| `low`    | 128k   | 96k    | 64k    |
| `medium` | 192k   | 144k   | 96k    |
| `high`   | 256k   | 192k   | 128k   |
| `best`   | 320k   | 256k   | 160k   |

AAC and Opus are more efficient codecs than MP3 — they achieve the same perceived quality at lower bitrates. The quality tiers account for this automatically.

Use `-b` to override with an explicit bitrate if you prefer.

## Dependencies

| Package | What it does |
|---------|-------------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Core download engine. Extracts audio streams from YouTube, handles playlist pagination, and embeds metadata/thumbnails via post-processors. Fork of youtube-dl with active maintenance. |
| [ffmpeg](https://ffmpeg.org/) | Audio Swiss army knife (system binary, not a Python package). Called by yt-dlp for extracting audio from video containers, and called directly by the converter for re-encoding between formats. Also handles thumbnail embedding via `EmbedThumbnail` post-processor. |
| [ffprobe](https://ffmpeg.org/) | Companion to ffmpeg (installed alongside it). Used by the converter to inspect existing files — reads bitrate, sample rate, codec, and duration to determine which duplicate is higher quality. |
| [click](https://click.palletsprojects.com/) | CLI framework. Handles argument parsing, subcommands (`list`, `download`, `convert`, `serve`), option validation, and help text generation. |
| [rich](https://rich.readthedocs.io/) | Terminal UI. Provides the progress bars, spinners, colored output, and formatted tables you see during downloads and conversions. |

## Project structure

```
yt_music/
├── pyproject.toml
├── src/yt_music/
│   ├── cli.py          # CLI entry point (click)
│   ├── playlist.py     # Fetch playlist metadata via yt-dlp
│   ├── downloader.py   # Parallel audio downloads
│   ├── converter.py    # Parallel format conversion + dedup
│   └── server.py       # HTTP server for mobile access
└── downloads/          # Default output directory
```
