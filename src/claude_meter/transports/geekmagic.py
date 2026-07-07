"""HTTP upload to a GeeKmagic SmallTV clock.

The stock firmware accepts POST /upload with multipart field "imageFile".
The filename picks which slot to overwrite:
  - "gif.jpg"              -> main-screen Customization GIF slot. The body
                              must be the firmware's custom animated-GIF
                              container: [frame0 JPEG][2400-byte index
                              block][frame1]...[frameN-1]. Index layout
                              per 12-byte record: <u16 0x01ff> <u16 id>
                              <u32 offset> <u32 size>. Record 0's `id`
                              holds the total frame count; records 1..N-1
                              hold absolute offsets. Frame count must be
                              >= a device-specific minimum (33 works).
  - "file1.jpg".."file5.jpg" -> Photo-mode full-screen slots (plain JPEG).
Max 1 MB per the device's JS check.
"""
from __future__ import annotations

import struct

import requests

GIF_INDEX_SIZE  = 2400
GIF_FRAME_COUNT = 33


class GeekmagicTransport:
    def __init__(self, host: str, mode: str):
        """
        host: "192.168.1.50" or "http://192.168.1.50" (your clock's IP)
        mode: "gif80" -> writes gif.jpg with container wrap (single frame
                         aliased across the index, since the card is static);
              "photo240" -> writes file1.jpg as-is;
              "visual_story" -> writes gif.jpg with a real multi-frame
                         container built from a list of distinct frames, so
                         the device actually animates the dance/wave/party
                         cycle instead of showing one static image.
        """
        if not host.startswith("http"):
            host = f"http://{host}"
        self._url  = f"{host.rstrip('/')}/upload"
        self._mode = mode

    def push(self, payload) -> int:
        if self._mode == "gif80":
            body = _build_gif_container(payload)
            filename = "gif.jpg"
        elif self._mode == "photo240":
            body = payload
            filename = "file1.jpg"
        elif self._mode == "visual_story":
            # payload is a list of raw PIL Images (see renderers/visual_story.py);
            # this firmware's container wants pinned-qtable JPEG frames.
            from claude_meter.renderers.visual_story import encode_jpeg_frame
            body = _build_animated_gif_container([encode_jpeg_frame(f) for f in payload])
            filename = "gif.jpg"
        else:
            raise ValueError(f"unsupported mode for geekmagic: {self._mode!r}")

        # The firmware often sends a truncated HTTP response after a
        # successful write — status line + headers, then it closes the
        # socket mid-body. Stream the response so we read only the
        # status and headers and never the body; otherwise a perfectly
        # good upload surfaces as a ChunkedEncodingError. timeout is
        # (connect, read-headers): the device can be slow to reply
        # while it commits the image to flash.
        resp = requests.post(
            self._url,
            files={"imageFile": (filename, body, "image/jpeg")},
            timeout=(5, 15),
            stream=True,
        )
        try:
            resp.raise_for_status()
        finally:
            resp.close()
        return len(body)


def _build_gif_container(frame: bytes, count: int = GIF_FRAME_COUNT) -> bytes:
    """
    Wrap a single JPEG frame in the firmware's container format.

    The usage card is static, so all `count` frames are byte-identical.
    Instead of shipping `count` physical copies, lay down one frame and
    alias every index record back at it (offset 0). The index still
    declares `count` frames so the firmware's minimum-frame check passes,
    but the upload carries one frame instead of `count` — roughly 88 KB
    down to ~5 KB, so the device writes far less flash per push.

    Layout: frame0 | 2400-byte index. Every record -> (offset 0, f_size).
    """
    f_size = len(frame)
    idx    = bytearray(GIF_INDEX_SIZE)
    # Record 0: id = total frame count; offset/size point at frame0.
    struct.pack_into("<HHII", idx, 0, 0x01ff, count, 0, f_size)
    # Records 1..count-1: alias every frame back to frame0 at offset 0.
    for k in range(1, count):
        struct.pack_into("<HHII", idx, k * 12, 0x01ff, k, 0, f_size)
    return frame + bytes(idx)


def _build_animated_gif_container(frames: list[bytes]) -> bytes:
    """
    Wrap distinct JPEG frames in the firmware's container format so the
    device plays a real animation instead of one static image repeated.

    Layout: frame0 | 2400-byte index | frame1 | frame2 | ... | frameN-1.
    Record 0 holds (id=count, offset=0, size=len(frame0)). Records 1..N-1
    hold the absolute offset/size of each subsequent frame, which sit after
    the index block in upload order.
    """
    count = len(frames)
    if count < 1:
        raise ValueError("need at least one frame")

    frame0 = frames[0]
    idx = bytearray(GIF_INDEX_SIZE)
    struct.pack_into("<HHII", idx, 0, 0x01ff, count, 0, len(frame0))

    tail = bytearray()
    offset = len(frame0) + GIF_INDEX_SIZE
    for k in range(1, count):
        f = frames[k]
        struct.pack_into("<HHII", idx, k * 12, 0x01ff, k, offset, len(f))
        tail += f
        offset += len(f)

    return frame0 + bytes(idx) + bytes(tail)
