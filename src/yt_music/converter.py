"""Standalone audio converter for re-encoding existing files via ffmpeg."""

from __future__ import annotations

import json
import re
import subprocess
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()

FFMPEG_CODECS = {
    "mp3": {"codec": "libmp3lame", "ext": "mp3"},
    "aac": {"codec": "aac", "ext": "m4a"},
    "opus": {"codec": "libopus", "ext": "opus"},
}

# Perceptually equivalent bitrates per codec at each quality tier.
# AAC and Opus are more efficient than MP3, so they need lower bitrates
# to achieve the same perceived quality.
#   - MP3:  lossy, oldest, needs highest bitrate
#   - AAC:  ~25-30% more efficient than MP3
#   - Opus: ~40-50% more efficient than MP3
QUALITY_TIERS = {
    "low":    {"mp3": "128", "aac": "96",  "opus": "64"},
    "medium": {"mp3": "192", "aac": "144", "opus": "96"},
    "high":   {"mp3": "256", "aac": "192", "opus": "128"},
    "best":   {"mp3": "320", "aac": "256", "opus": "160"},
}

DEFAULT_QUALITY = "best"


def resolve_bitrate(audio_format: str, bitrate: str | None, quality: str | None) -> str:
    """Resolve a bitrate from explicit value or quality tier.

    If bitrate is given, use it directly. Otherwise map the quality tier
    to the appropriate bitrate for the codec.
    """
    if bitrate:
        return bitrate
    q = (quality or DEFAULT_QUALITY).lower()
    tier = QUALITY_TIERS.get(q, QUALITY_TIERS[DEFAULT_QUALITY])
    return tier.get(audio_format, tier["mp3"])


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def probe_audio(path: Path) -> dict | None:
    """Use ffprobe to get audio stream info (bitrate, codec, duration, sample_rate)."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        "-select_streams", "a:0",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        return {
            "path": path,
            "codec": stream.get("codec_name", ""),
            "bit_rate": int(stream.get("bit_rate") or fmt.get("bit_rate") or 0),
            "sample_rate": int(stream.get("sample_rate") or 0),
            "duration": float(fmt.get("duration") or 0),
            "size": path.stat().st_size,
        }
    except Exception:
        return None


def _normalize_stem(stem: str) -> str:
    """Normalize a filename stem for duplicate comparison.

    Strips common suffixes like '(1)', '(Official Audio)', codec tags, etc.
    and lowercases for case-insensitive matching.
    """
    s = stem.lower()
    # Remove trailing parenthesised tags: (Official Audio), (HQ), (1), etc.
    s = re.sub(r"\s*\((?:official\s*(?:audio|video|music\s*video)|hq\s*audio|hq|lyric(?:s)?|audio|video|\d+)\)\s*", " ", s)
    # Remove trailing bracket tags: [Official Audio], etc.
    s = re.sub(r"\s*\[(?:official\s*(?:audio|video)|hq|lyrics?|audio|video|\d+)\]\s*", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _score_file(info: dict) -> tuple[int, int, int]:
    """Return a sort key (higher = better quality)."""
    return (info["bit_rate"], info["sample_rate"], info["size"])


def deduplicate(files: list[Path]) -> tuple[list[Path], list[tuple[Path, Path]]]:
    """Find duplicates by normalized stem and pick the best quality for each.

    Returns (best_files, replacements) where replacements is a list of
    (kept_path, removed_path) pairs for reporting.
    """
    # Group files by normalized stem
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        key = _normalize_stem(f.stem)
        groups[key].append(f)

    best_files: list[Path] = []
    replacements: list[tuple[Path, Path]] = []

    for key, paths in groups.items():
        if len(paths) == 1:
            best_files.append(paths[0])
            continue

        # Probe all candidates
        probed = []
        for p in paths:
            info = probe_audio(p)
            if info:
                probed.append(info)
            else:
                # Can't probe — keep it as a fallback
                probed.append({
                    "path": p, "bit_rate": 0, "sample_rate": 0,
                    "size": p.stat().st_size, "codec": "", "duration": 0,
                })

        # Sort by quality score, best last
        probed.sort(key=_score_file)
        winner = probed[-1]
        best_files.append(winner["path"])

        for loser in probed[:-1]:
            replacements.append((winner["path"], loser["path"]))

    return sorted(best_files, key=lambda f: f.name), replacements


def convert_file(
    input_path: Path,
    output_format: str,
    bitrate: str | None = None,
    quality: str | None = None,
    output_dir: Path | None = None,
) -> Path | None:
    """Convert an audio file to the specified format.

    Returns the output path on success, None on failure.
    """
    if not check_ffmpeg():
        console.print("[red]Error: ffmpeg not found. Install it first.[/]")
        return None

    fmt = FFMPEG_CODECS.get(output_format)
    if fmt is None:
        console.print(f"[red]Unsupported format: {output_format}[/]")
        return None

    br = resolve_bitrate(output_format, bitrate, quality)

    dest_dir = output_dir or input_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    output_path = dest_dir / f"{input_path.stem}.{fmt['ext']}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",                     # no video
        "-c:a", fmt["codec"],      # audio codec
        "-b:a", f"{br}k",          # bitrate
        "-map_metadata", "0",      # preserve metadata
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            console.print(f"[red]ffmpeg error for {input_path.name}:[/] {result.stderr[:200]}")
            return None
        return output_path
    except subprocess.TimeoutExpired:
        console.print(f"[red]Timeout converting {input_path.name}[/]")
        return None


def convert_directory(
    input_dir: Path,
    output_format: str,
    bitrate: str | None = None,
    quality: str | None = None,
    output_dir: Path | None = None,
    workers: int = 4,
) -> list[Path]:
    """Convert all audio files in a directory. Returns list of output paths."""
    br = resolve_bitrate(output_format, bitrate, quality)
    audio_extensions = {".mp3", ".m4a", ".opus", ".ogg", ".webm", ".wav", ".flac", ".aac"}
    files = sorted(f for f in input_dir.iterdir() if f.suffix.lower() in audio_extensions)

    if not files:
        console.print(f"[yellow]No audio files found in {input_dir}[/]")
        return []

    # Deduplicate — pick best quality from each group of similar filenames
    console.print(f"[dim]Scanning {len(files)} audio files for duplicates...[/]")
    best_files, replacements = deduplicate(files)

    if replacements:
        console.print(f"\n[bold yellow]Found {len(replacements)} duplicate(s) — keeping best quality:[/]")
        for kept, removed in replacements:
            kept_info = probe_audio(kept)
            removed_info = probe_audio(removed)
            kept_br = f"{kept_info['bit_rate'] // 1000}k" if kept_info else "?"
            removed_br = f"{removed_info['bit_rate'] // 1000}k" if removed_info else "?"
            console.print(f"  [green]✓ KEEP[/]   {kept.name} ({kept_br})")
            console.print(f"  [red]✗ SKIP[/]   {removed.name} ({removed_br})")
    else:
        console.print(f"[dim]No duplicates found.[/]")

    q_label = (quality or DEFAULT_QUALITY).lower() if not bitrate else "custom"
    console.print(f"\nConverting {len(best_files)} files → [cyan]{output_format.upper()}[/] "
                  f"@ [cyan]{br}kbps[/] (quality: {q_label})")
    console.print(f"[dim]Workers: {workers}[/]\n")

    results: list[Path] = []
    errors: list[str] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[dim]{task.completed}/{task.total}[/]"),
        console=console,
    ) as progress:
        task = progress.add_task("Converting...", total=len(best_files))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(convert_file, f, output_format, br, None, output_dir): f
                for f in best_files
            }

            for fut in as_completed(futures):
                src = futures[fut]
                out = fut.result()
                if out:
                    results.append(out)
                    progress.update(task, description=f"[green]✓[/] {out.name[:55]}")
                else:
                    errors.append(src.name)
                    progress.update(task, description=f"[red]✗[/] {src.name[:55]}")
                progress.advance(task)

    console.print(f"\n[bold green]Converted {len(results)}/{len(best_files)} files[/]")
    if errors:
        console.print(f"[bold yellow]⚠ {len(errors)} failed:[/]")
        for name in errors:
            console.print(f"  [dim red]{name}[/]")
    if replacements:
        console.print(f"[dim]{len(replacements)} lower-quality duplicate(s) were skipped[/]")
    return results
