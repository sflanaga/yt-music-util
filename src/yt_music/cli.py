"""CLI entry point for yt-music."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from yt_music.playlist import fetch_playlist
from yt_music.downloader import download_playlist, FORMATS
from yt_music.converter import convert_directory, check_ffmpeg, QUALITY_TIERS

console = Console()


@click.group()
@click.version_option(package_name="yt-music")
def main() -> None:
    """Download YouTube Music playlists and convert to mp3/aac."""


@main.command(name="list")
@click.option("--playlist", "-p", required=True, help="YouTube Music playlist URL or ID")
def list_tracks(playlist: str) -> None:
    """List all tracks in a playlist without downloading."""
    pl = fetch_playlist(playlist)

    table = Table(title=f"{pl.title} — {pl.uploader or 'Unknown'}")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Artist")
    table.add_column("Duration", justify="right")

    for i, track in enumerate(pl.tracks, 1):
        table.add_row(str(i), track.title, track.artist or "—", track.duration_str)

    console.print(table)
    console.print(f"\n[bold]{len(pl.tracks)} tracks[/] • {pl.total_duration_str}")


@main.command()
@click.option("--playlist", "-p", required=True, help="YouTube Music playlist URL or ID")
@click.option(
    "--format", "-f", "audio_format",
    type=click.Choice(list(FORMATS.keys()), case_sensitive=False),
    default="mp3",
    show_default=True,
    help="Output audio format",
)
@click.option(
    "--quality", "-q",
    type=click.Choice(list(QUALITY_TIERS.keys()), case_sensitive=False),
    default="best",
    show_default=True,
    help="Quality tier (auto-selects optimal bitrate per codec)",
)
@click.option("--bitrate", "-b", default=None, help="Override bitrate in kbps (ignores quality tier)")
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=Path("downloads"),
    show_default=True,
    help="Output directory",
)
@click.option(
    "--workers", "-w",
    type=click.IntRange(1, 16),
    default=4,
    show_default=True,
    help="Parallel download workers",
)
def download(playlist: str, audio_format: str, quality: str, bitrate: str | None, output: Path, workers: int) -> None:
    """Download all tracks from a playlist."""
    if not check_ffmpeg():
        console.print("[bold red]Error:[/] ffmpeg is required but not found on PATH.")
        console.print("Install it: [cyan]sudo apt install ffmpeg[/] or [cyan]brew install ffmpeg[/]")
        raise SystemExit(1)

    download_playlist(
        playlist_url=playlist,
        output_dir=output,
        audio_format=audio_format,
        bitrate=bitrate,
        quality=quality,
        workers=workers,
    )


@main.command()
@click.option(
    "--input", "-i", "input_dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory containing audio files to convert",
)
@click.option(
    "--format", "-f", "audio_format",
    type=click.Choice(["mp3", "aac", "opus"], case_sensitive=False),
    required=True,
    help="Target audio format",
)
@click.option(
    "--quality", "-q",
    type=click.Choice(list(QUALITY_TIERS.keys()), case_sensitive=False),
    default="best",
    show_default=True,
    help="Quality tier (auto-selects optimal bitrate per codec)",
)
@click.option("--bitrate", "-b", default=None, help="Override bitrate in kbps (ignores quality tier)")
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory (default: same as input)",
)
@click.option(
    "--workers", "-w",
    type=click.IntRange(1, 16),
    default=4,
    show_default=True,
    help="Parallel conversion workers",
)
def convert(input_dir: Path, audio_format: str, quality: str, bitrate: str | None, output: Path | None, workers: int) -> None:
    """Convert existing audio files to a different format."""
    if not check_ffmpeg():
        console.print("[bold red]Error:[/] ffmpeg is required but not found on PATH.")
        raise SystemExit(1)

    convert_directory(input_dir, audio_format, bitrate=bitrate, quality=quality, output_dir=output, workers=workers)


@main.command()
@click.option(
    "--input", "-i", "music_dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory containing audio files to serve",
)
@click.option("--port", "-p", default=8000, show_default=True, help="HTTP port")
def serve(music_dir: Path, port: int) -> None:
    """Start an HTTP server to browse/download music from your phone."""
    from yt_music.server import serve as start_server
    start_server(music_dir, port=port)


if __name__ == "__main__":
    main()
