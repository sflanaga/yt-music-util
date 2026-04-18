"""Fetch playlist metadata using yt-dlp (no auth required for public playlists)."""

from __future__ import annotations

from dataclasses import dataclass

import yt_dlp
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()


@dataclass
class Track:
    """Metadata for a single track in a playlist."""

    video_id: str
    title: str
    artist: str | None
    album: str | None
    duration: int | None  # seconds
    url: str

    @property
    def duration_str(self) -> str:
        if self.duration is None:
            return "?"
        m, s = divmod(self.duration, 60)
        return f"{m}:{s:02d}"


@dataclass
class Playlist:
    """Playlist metadata and track listing."""

    playlist_id: str
    title: str
    uploader: str | None
    tracks: list[Track]

    @property
    def total_duration_str(self) -> str:
        total = sum(t.duration for t in self.tracks if t.duration)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m"
        return f"{m}m {s}s"


def fetch_playlist(playlist_url: str) -> Playlist:
    """Extract playlist info and all track metadata without downloading."""
    # Step 1: Quick flat extract to get track count and playlist title
    console.print(f"[dim]Connecting to YouTube Music...[/]")
    flat_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": None,
    }
    with yt_dlp.YoutubeDL(flat_opts) as ydl:
        flat_info = ydl.extract_info(playlist_url, download=False)

    if flat_info is None:
        raise RuntimeError(f"Could not fetch playlist: {playlist_url}")

    flat_entries = [e for e in (flat_info.get("entries") or []) if e is not None]
    total = len(flat_entries)
    playlist_title = flat_info.get("title", "Unknown Playlist")
    playlist_uploader = flat_info.get("uploader")

    console.print(f"[bold]{playlist_title}[/] by [cyan]{playlist_uploader or 'Unknown'}[/]")
    console.print(f"[dim]Found {total} tracks — fetching metadata...[/]\n")

    # Step 2: Fetch full metadata for each track with progress
    single_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": True,
    }

    tracks: list[Track] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[dim]{task.completed}/{task.total}[/]"),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching track info...", total=total)

        for i, flat_entry in enumerate(flat_entries, 1):
            video_id = flat_entry.get("id") or flat_entry.get("url", "")
            title = flat_entry.get("title", video_id)
            progress.update(task, description=f"[{i}/{total}] {title[:55]}")

            url = f"https://www.youtube.com/watch?v={video_id}"
            try:
                with yt_dlp.YoutubeDL(single_opts) as ydl:
                    entry = ydl.extract_info(url, download=False)
            except Exception:
                entry = None

            if entry is not None:
                tracks.append(
                    Track(
                        video_id=entry.get("id", video_id),
                        title=entry.get("title", title),
                        artist=entry.get("artist") or entry.get("uploader"),
                        album=entry.get("album"),
                        duration=entry.get("duration"),
                        url=url,
                    )
                )
            else:
                console.print(f"  [yellow]⚠ Skipped (unavailable):[/] {title}")

            progress.advance(task)

    console.print(f"\n[green]✓ Fetched metadata for {len(tracks)}/{total} tracks[/]")

    return Playlist(
        playlist_id=flat_info.get("id", ""),
        title=playlist_title,
        uploader=playlist_uploader,
        tracks=tracks,
    )
