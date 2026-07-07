"""HTTP upload to a GeekMagic SmallTV *Ultra* clock.

This is a different device/firmware from transports/geekmagic.py's target
(see that module's docstring): the Ultra's web UI (served at /image.html,
driven by /js/settings.js on the device itself) uses a plain multipart file
upload, not a custom binary container with pinned quantization tables. It
accepts an ordinary animated GIF directly.

There's no public API doc for this firmware -- this was reverse-engineered
by reading the device's own served HTML/JS, then confirmed live against a
real Ultra-V9.0.50 unit. Three-step protocol:
  1. POST /doUpload?dir=<dir>   multipart field "image" -> <filename>.gif
     Saves the file into the device's on-flash image directory.
  2. GET  /set?theme=3
     Switches the device to the "Photo Album" theme (theme 3 in the
     device's own theme list). Uploading alone doesn't display anything;
     the device stays on whatever theme it was already showing.
  3. GET  /set?img=<full path, e.g. /image/foo.gif>
     Selects the uploaded file as the active Photo Album image.

Two things that looked plausible but verified false against the real
device (checked via GET /app.json, which reports {"theme": N}):
  - Combining img= and theme= in a single /set call: only one of the two
    takes effect. They must be two separate requests.
  - Passing the bare filename to img=: the device's own "Set" button in
    its file list passes the *full* path (e.g. "/image/foo.gif"), and the
    bare filename silently no-ops.

The /doUpload response also has a firmware bug: it sends two conflicting
Content-Length headers (confirmed with curl -i -- e.g. "984" then "11").
requests/urllib3 refuses to parse that and raises InvalidHeader before we
ever see a response, even though the write itself already completed. GET
/filelist and /set responses don't have this problem, so on that specific
failure we verify the write out-of-band via /filelist instead of trusting
the HTTP response.

Firmware repo: https://github.com/GeekMagicClock/smalltv-ultra
"""
from __future__ import annotations

import io

import requests
from PIL import Image

IMAGE_DIR         = "/image/"
PHOTO_ALBUM_THEME = 3
FRAME_DURATION_MS = 90


class SmallTVUltraTransport:
    def __init__(self, host: str, mode: str, filename: str = "claude_meter.gif"):
        """
        host: "192.168.1.50" or "http://192.168.1.50" (your clock's IP)
        mode: unused (kept for the same call signature as GeekmagicTransport,
              see transports/__init__.get()) -- this firmware only ever
              displays a single active image, so there's nothing to switch on.
        """
        if not host.startswith("http"):
            host = f"http://{host}"
        self._base     = host.rstrip("/")
        self._filename = filename

    def push(self, frames: list[Image.Image]) -> int:
        gif_bytes = _build_gif(frames)
        full_path = IMAGE_DIR + self._filename

        self._upload(gif_bytes)

        theme = requests.get(
            f"{self._base}/set", params={"theme": PHOTO_ALBUM_THEME}, timeout=(5, 10))
        theme.raise_for_status()

        activate = requests.get(
            f"{self._base}/set", params={"img": full_path}, timeout=(5, 10))
        activate.raise_for_status()

        return len(gif_bytes)

    def _upload(self, gif_bytes: bytes) -> None:
        try:
            resp = requests.post(
                f"{self._base}/doUpload",
                params={"dir": IMAGE_DIR},
                files={"image": (self._filename, gif_bytes, "image/gif")},
                timeout=(5, 20),
            )
            resp.raise_for_status()
        except requests.exceptions.InvalidHeader:
            if not self._file_present():
                raise

    def _file_present(self) -> bool:
        try:
            resp = requests.get(
                f"{self._base}/filelist", params={"dir": IMAGE_DIR}, timeout=(5, 10))
            resp.raise_for_status()
        except requests.exceptions.RequestException:
            return False
        return self._filename in resp.text


def _build_gif(frames: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:],
        duration=FRAME_DURATION_MS, loop=0, disposal=2,
    )
    return buf.getvalue()
