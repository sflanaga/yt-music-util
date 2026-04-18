"""Simple HTTP server to serve downloaded music files to mobile devices."""

from __future__ import annotations

import io
import socket
import zipfile
from pathlib import Path

from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import quote, unquote

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".opus", ".ogg", ".aac", ".flac", ".wav"}

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🎵 {title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #1a1a2e; color: #eee; padding: 16px; }}
  h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
  .subtitle {{ color: #888; font-size: 0.9em; margin-bottom: 16px; }}
  .actions {{ margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
  .btn {{ display: inline-block; padding: 10px 20px; border-radius: 8px; text-decoration: none;
          font-weight: 600; font-size: 0.95em; }}
  .btn-primary {{ background: #e94560; color: #fff; }}
  .btn-secondary {{ background: #16213e; color: #0f3460; border: 1px solid #0f3460; color: #eee; }}
  .list {{ list-style: none; }}
  .list li {{ padding: 12px; border-bottom: 1px solid #16213e; display: flex;
              justify-content: space-between; align-items: center; gap: 8px; }}
  .list li:last-child {{ border-bottom: none; }}
  .track-name {{ flex: 1; font-size: 0.95em; word-break: break-word; }}
  .track-size {{ color: #888; font-size: 0.8em; white-space: nowrap; }}
  .dl {{ color: #e94560; text-decoration: none; font-size: 0.9em; white-space: nowrap; }}
  audio {{ width: 100%; max-width: 300px; height: 32px; }}
  .player {{ margin-top: 4px; }}
  .now-playing {{ background: #16213e; padding: 12px; border-radius: 8px; margin-bottom: 16px;
                  display: none; }}
  .now-playing.active {{ display: block; }}
  .np-title {{ font-weight: 600; margin-bottom: 8px; }}
</style>
</head>
<body>
<h1>🎵 {title}</h1>
<p class="subtitle">{count} tracks &middot; {total_size}</p>

<div class="actions">
  <a class="btn btn-primary" href="/download-all">⬇ Download All (ZIP)</a>
</div>

<div id="now-playing" class="now-playing">
  <div class="np-title" id="np-title"></div>
  <audio id="player" controls preload="none"></audio>
</div>

<ul class="list">
{track_rows}
</ul>

<script>
const player = document.getElementById('player');
const npDiv = document.getElementById('now-playing');
const npTitle = document.getElementById('np-title');

document.querySelectorAll('.play-btn').forEach(btn => {{
  btn.addEventListener('click', e => {{
    e.preventDefault();
    const src = btn.dataset.src;
    const name = btn.dataset.name;
    player.src = src;
    player.play();
    npTitle.textContent = '▶ ' + name;
    npDiv.classList.add('active');
  }});
}});
</script>
</body>
</html>
"""

TRACK_ROW = """\
<li>
  <span class="track-name">
    <a href="#" class="play-btn" data-src="/file/{encoded}" data-name="{name}"
       style="color:#eee;text-decoration:none">▶</a>
    {name}
  </span>
  <span class="track-size">{size}</span>
  <a class="dl" href="/file/{encoded}" download>⬇</a>
</li>"""


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _get_local_ip() -> str:
    """Get the LAN IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class MusicHandler(SimpleHTTPRequestHandler):
    """Handler that serves an index page, individual files, and a ZIP download."""

    music_dir: Path  # set by serve()

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._serve_index()
        elif self.path == "/download-all":
            self._serve_zip()
        elif self.path.startswith("/file/"):
            self._serve_file()
        else:
            self.send_error(404)

    def _get_audio_files(self) -> list[Path]:
        return sorted(
            f for f in self.music_dir.iterdir()
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        )

    def _serve_index(self) -> None:
        files = self._get_audio_files()
        total_size = sum(f.stat().st_size for f in files)

        rows = []
        for f in files:
            rows.append(TRACK_ROW.format(
                name=f.name,
                encoded=quote(f.name),
                size=_human_size(f.stat().st_size),
            ))

        html = HTML_TEMPLATE.format(
            title=self.music_dir.name,
            count=len(files),
            total_size=_human_size(total_size),
            track_rows="\n".join(rows),
        )

        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self) -> None:
        filename = unquote(self.path[len("/file/"):])
        filepath = self.music_dir / filename

        # Prevent path traversal
        try:
            filepath.resolve().relative_to(self.music_dir.resolve())
        except ValueError:
            self.send_error(403, "Forbidden")
            return

        if not filepath.is_file():
            self.send_error(404)
            return

        size = filepath.stat().st_size
        content_type = {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".opus": "audio/ogg",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".wav": "audio/wav",
        }.get(filepath.suffix.lower(), "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'inline; filename="{filepath.name}"')
        self.end_headers()

        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

    def _serve_zip(self) -> None:
        files = self._get_audio_files()
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for f in files:
                zf.write(f, f.name)

        data = buf.getvalue()
        zip_name = f"{self.music_dir.name}.zip"

        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        # Quieter logging — just method + path
        pass


def serve(music_dir: Path, port: int = 8000, bind: str = "0.0.0.0") -> None:
    """Start the HTTP server."""
    MusicHandler.music_dir = music_dir.resolve()

    local_ip = _get_local_ip()
    server = HTTPServer((bind, port), MusicHandler)

    print(f"\n🎵 Serving {music_dir.name}")
    print(f"   Local:   http://localhost:{port}")
    print(f"   Network: http://{local_ip}:{port}")
    print(f"\n   Open the Network URL on your iPhone!")
    print(f"   Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
