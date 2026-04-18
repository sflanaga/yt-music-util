"""Download audio tracks from YouTube using yt-dlp."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yt_dlp
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()

from yt_music.converter import QUALITY_TIERS, DEFAULT_QUALITY, resolve_bitrate

# Supported output formats and their yt-dlp audio codec names
FORMATS = {
    "mp3": {"codec": "mp3", "ext": "mp3"},
    "aac": {"codec": "aac", "ext": "m4a"},
    "opus": {"codec": "opus", "ext": "opus"},
    "best": {"codec": "best", "ext": None},  # keep original
}


def _build_output_template(output_dir: Path) -> str:
    """Build yt-dlp output template: Artist - Title.ext"""
    return str(output_dir / "%(artist,uploader)s - %(title)s.%(ext)s")


def _build_ydl_opts(
    output_dir: Path,
    audio_format: str,
    bitrate: str | None,
    quality: str | None = None,
    progress_hook: callable | None = None,
) -> dict:
    """Build the yt-dlp options dict."""
    fmt_info = FORMATS.get(audio_format, FORMATS["mp3"])
    br = resolve_bitrate(audio_format, bitrate, quality)

    postprocessors = []

    # Extract audio from video container
    pp_extract = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": fmt_info["codec"],
        "preferredquality": br,
    }
    postprocessors.append(pp_extract)

    # Embed metadata (title, artist, album, etc.)
    postprocessors.append({"key": "FFmpegMetadata"})

    # Embed thumbnail as cover art
    postprocessors.append({"key": "EmbedThumbnail"})

    opts = {
        "format": "bestaudio/best",
        "outtmpl": _build_output_template(output_dir),
        "writethumbnail": True,
        "postprocessors": postprocessors,
        "ignoreerrors": True,
        "no_warnings": True,
        "quiet": True,
        "noprogress": True,
    }

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    return opts


def _find_existing(output_dir: Path, title: str, artist: str | None, audio_format: str) -> Path | None:
    """Check if a track has already been downloaded.

    Scans the output directory for files whose stem matches the expected
    naming pattern (Artist - Title) or just the title portion.
    """
    fmt_info = FORMATS.get(audio_format, FORMATS["mp3"])
    # Expected extensions for each format
    extensions = set()
    if fmt_info["ext"]:
        extensions.add(f".{fmt_info['ext']}")
    # Also check common audio extensions in case format changed between runs
    extensions.update({".mp3", ".m4a", ".opus", ".ogg", ".webm"})

    # Build patterns to match against
    patterns: list[str] = []
    if artist:
        patterns.append(f"{artist} - {title}")
    patterns.append(title)

    for f in output_dir.iterdir():
        if f.suffix.lower() not in extensions:
            continue
        stem = f.stem.lower()
        for pat in patterns:
            if pat.lower() in stem or stem in pat.lower():
                return f
    return None


def _download_one(
    url: str,
    title: str,
    artist: str | None,
    output_dir: Path,
    audio_format: str,
    bitrate: str | None,
    quality: str | None,
) -> tuple[str, str | None, str | None]:
    """Download a single track. Returns (title, filepath_or_None, error_or_None)."""
    # Check for existing file first
    existing = _find_existing(output_dir, title, artist, audio_format)
    if existing:
        return (title, str(existing), None)

    result_path: dict = {"path": None}

    def hook(d: dict) -> None:
        if d["status"] == "finished":
            result_path["path"] = d.get("filename")

    opts = _build_ydl_opts(output_dir, audio_format, bitrate, quality, hook)
    opts["noplaylist"] = True

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return (title, result_path["path"], None)
    except Exception as e:
        return (title, None, str(e))


def download_playlist(
    playlist_url: str,
    output_dir: Path,
    audio_format: str = "mp3",
    bitrate: str | None = None,
    quality: str | None = None,
    workers: int = 4,
) -> list[str]:
    """Download all tracks from a playlist URL.

    Returns list of successfully downloaded file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []

    br = resolve_bitrate(audio_format, bitrate, quality)

    # First, get playlist info to know total count
    info_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": None,
    }
    with yt_dlp.YoutubeDL(info_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    total_tracks = len(info.get("entries") or []) if info else 0

    q_label = (quality or DEFAULT_QUALITY).lower() if not bitrate else "custom"
    console.print(f"\n[bold green]Downloading {total_tracks} tracks[/] "
                  f"→ [cyan]{audio_format.upper()}[/] @ [cyan]{br}kbps[/] (quality: {q_label})")
    console.print(f"[dim]Output: {output_dir.resolve()}[/]")
    console.print(f"[dim]Workers: {workers}[/]\n")

    # Build work items
    entries = (info.get("entries") or []) if info else []
    errors: list[str] = []
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[dim]{task.completed}/{task.total}[/]"),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading...", total=total_tracks)

        # Submit all downloads to thread pool
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for entry in entries:
                if entry is None:
                    progress.advance(task)
                    continue
                video_id = entry.get("id") or entry.get("url", "")
                title = entry.get("title", video_id)
                url = f"https://www.youtube.com/watch?v={video_id}"
                fut = pool.submit(
                    _download_one, url, title, None,
                    output_dir, audio_format, bitrate, quality,
                )
                futures[fut] = title

            for fut in as_completed(futures):
                title, path, error = fut.result()
                if error:
                    errors.append(f"{title}: {error}")
                elif path:
                    downloaded.append(path)
                    # Detect if it was a skip (file existed before download)
                    existing = _find_existing(output_dir, title, None, audio_format)
                    if existing and str(existing) == path:
                        skipped += 1
                progress.update(task, description=f"{title[:55]}")
                progress.advance(task)

    new_downloads = len(downloaded) - skipped
    console.print(f"\n[bold green]✓ {new_downloads} new downloads[/]", end="")
    if skipped:
        console.print(f" • [dim]{skipped} skipped (already existed)[/]", end="")
    if errors:
        console.print(f" • [yellow]{len(errors)} errors[/]", end="")
    console.print()
    if errors:
        for err in errors:
            console.print(f"  [dim red]{err}[/]")

    return downloaded


def download_single(
    video_url: str,
    output_dir: Path,
    audio_format: str = "mp3",
    bitrate: str | None = None,
    quality: str | None = None,
) -> str | None:
    """Download a single track. Returns the output file path or None on error."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path: dict = {"path": None}

    def progress_hook(d: dict) -> None:
        if d["status"] == "finished":
            result_path["path"] = d.get("filename")

    opts = _build_ydl_opts(output_dir, audio_format, bitrate, quality, progress_hook)
    opts["noplaylist"] = True

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([video_url])
        return result_path["path"]
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        return None
