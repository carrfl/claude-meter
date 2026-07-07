"""Visual Story renderer for claude-meter.

Five scenes driven by the raw /api/oauth/usage response:
  safe / warn / alarm / waving / celebrate.
Sprite: Rocky (pixel dance loop) from ./assets/rocky_dancing.gif.

Unlike the other renderers (gif80, photo240) this one is animated, so it
exposes `render_frames(usage, size, n)` -> list[bytes] in addition to the
single-frame `render(...)` required by the shared Renderer protocol. Callers
that know about animation (loop.py) should prefer render_frames; render()
is a non-animated, non-celebrating fallback kept for protocol compliance.
"""
from __future__ import annotations

import io
import json
import math
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence

from claude_meter.renderers import load_font
from claude_meter.renderers.gif80 import APP0_BYTES, CHROMA_QTABLE, LUMA_QTABLE

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ASSET_PATH        = os.path.join(os.path.dirname(__file__),
                                 "assets", "rocky_dancing.gif")
ROCKY_H           = 64        # sprite height in px (64 reads cleanly at 240)
STATE_PATH        = Path.home() / ".claude-meter" / "state.json"
CELEBRATE_SECONDS = 600       # 10-minute post-reset party
RESET_WINDOW      = 300       # +/-5 min grace around computed weekly reset

# ---------------------------------------------------------------------------
# Sprite loading & pose synthesis
# ---------------------------------------------------------------------------
def _load_rocky_frames():
    """Load rocky_dancing.gif, key black->transparent, scale to ROCKY_H.

    The source frames are full 240x240 canvases with Rocky occupying only
    part of the frame (lots of black padding around him). Keying to alpha
    and then cropping every frame to the *union* bounding box (so the crop
    is identical across the whole loop -> no per-frame jitter) before
    resizing means the tiny on-device sprite spends its pixel budget on
    Rocky instead of on padding. LANCZOS (not NEAREST) because the source
    art is a detailed illustration, not a pre-sized pixel sprite -- nearest-
    neighbor on a ~4x downscale just aliased it into noise.
    """
    raw = []
    with Image.open(ASSET_PATH) as gif:
        for f in ImageSequence.Iterator(gif):
            rgba = f.convert("RGBA")
            px = rgba.load()
            w, h = rgba.size
            for y in range(h):
                for x in range(w):
                    r, g, b, _ = px[x, y]
                    if r < 24 and g < 24 and b < 24:
                        px[x, y] = (0, 0, 0, 0)
            raw.append(rgba)

    if not raw:
        return [Image.new("RGBA", (32, ROCKY_H), (0, 0, 0, 0))]

    boxes = [f.getbbox() for f in raw]
    boxes = [b for b in boxes if b is not None]
    if boxes:
        x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
    else:
        x0, y0, x1, y1 = 0, 0, raw[0].width, raw[0].height

    frames = []
    for rgba in raw:
        cropped = rgba.crop((x0, y0, x1, y1))
        ratio = ROCKY_H / cropped.height
        cropped = cropped.resize(
            (max(1, int(cropped.width * ratio)), ROCKY_H), Image.LANCZOS)
        frames.append(cropped)
    return frames


def _make_wave_pose(base):
    """Lift rightmost 30% of pixels 6px -> 'waving' silhouette."""
    pose = base.copy()
    w, h = pose.size
    strip = pose.crop((int(w * 0.7), 0, w, h))
    pose.paste(Image.new("RGBA", strip.size, (0, 0, 0, 0)),
               (int(w * 0.7), 0))
    pose.paste(strip, (int(w * 0.7), -6), strip)
    return pose


def _make_party_pose(base):
    """Lift both outer 30% strips 8px -> 'both legs up' celebration."""
    pose = base.copy()
    w, h = pose.size
    r = pose.crop((int(w * 0.7), 0, w, h))
    pose.paste(Image.new("RGBA", r.size, (0, 0, 0, 0)), (int(w * 0.7), 0))
    pose.paste(r, (int(w * 0.7), -8), r)
    l = pose.crop((0, 0, int(w * 0.3), h))
    pose.paste(Image.new("RGBA", l.size, (0, 0, 0, 0)), (0, 0))
    pose.paste(l, (0, -8), l)
    return pose


_ROCKY       = _load_rocky_frames()
_ROCKY_WAVE  = [_make_wave_pose(_ROCKY[0]),
                _make_wave_pose(_ROCKY[len(_ROCKY) // 2])]
_ROCKY_PARTY = [_make_party_pose(_ROCKY[0]),
                _make_party_pose(_ROCKY[len(_ROCKY) // 2])]

# ---------------------------------------------------------------------------
# Persistent state (for reset detection)
# ---------------------------------------------------------------------------
def _load_state():
    try:    return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError): return {}


def _save_state(s):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s))


def _is_celebrating(usage: dict) -> bool:
    now = time.time()
    p7  = usage["seven_day"]["utilization"]
    resets_at_raw = usage["seven_day"].get("resets_at") or ""

    state           = _load_state()
    prev_p7         = state.get("prev_p7", 0)
    celebrate_until = state.get("celebrate_until", 0)

    dropped    = prev_p7 >= 90 and p7 < 10
    near_reset = False
    if resets_at_raw:
        resets_at  = datetime.fromisoformat(resets_at_raw.replace("Z", "+00:00"))
        last_reset = (resets_at - timedelta(days=7)).timestamp()
        near_reset = abs(now - last_reset) <= RESET_WINDOW and p7 < 10

    if dropped or near_reset:
        celebrate_until = now + CELEBRATE_SECONDS

    _save_state({"prev_p7": p7, "celebrate_until": celebrate_until})
    return now < celebrate_until


# ---------------------------------------------------------------------------
# Speech bubble
# ---------------------------------------------------------------------------
def _speech_bubble(draw, xy, text, tone, size):
    palette = {
        "warn":  {"fill": (255, 220, 120), "border": (200, 160, 40),
                  "ink":  (30, 20, 0)},
        "alarm": {"fill": (255, 120, 110), "border": (170, 40, 40),
                  "ink":  (30, 0, 0)},
        "party": {"fill": (140, 240, 170), "border": (40, 150, 70),
                  "ink":  (0, 30, 10)},
    }[tone]

    font = load_font(9)
    tw = draw.textlength(text, font=font)
    pad = 5
    bw, bh = int(tw) + pad * 2, 20
    margin = 3
    bx = max(margin, min(size - margin - bw, xy[0] - bw // 2))
    by = xy[1] - bh - 6

    draw.rectangle((bx, by, bx + bw, by + bh),
                   fill=palette["fill"], outline=palette["border"], width=1)

    # Tail points at the true anchor (xy[0]), clamped to stay on the box.
    tx = max(bx + 6, min(bx + bw - 6, xy[0]))
    for i, dx in enumerate((0, 1, 2)):
        draw.rectangle((tx - 2 + dx, by + bh + i,
                        tx + 2 - dx, by + bh + i + 1),
                       fill=palette["fill"])
        draw.point((tx - 2 + dx - 1, by + bh + i), fill=palette["border"])
        draw.point((tx + 2 - dx,     by + bh + i), fill=palette["border"])

    draw.text((bx + pad, by + 4), text, font=font, fill=palette["ink"])


def _warning_text(p5, p7):
    worst = max(p5, p7)
    if worst >= 95: return ("STOP! QUESTION?", "alarm")
    if worst >= 85: return ("SLOW! QUESTION?", "warn")
    return (None, None)


# ---------------------------------------------------------------------------
# Celebration FX
# ---------------------------------------------------------------------------
def _draw_confetti(d, size, frame_idx):
    rng = random.Random(1000 + frame_idx)
    palette = [(255, 90, 90), (255, 200, 80), (120, 220, 140),
               (90, 180, 255), (220, 130, 255)]
    for _ in range(45):
        x = rng.randint(4, size - 4)
        y = rng.randint(4, size - 60)
        c = rng.choice(palette)
        d.rectangle((x, y, x + 1, y + 1), fill=c)


def _draw_starburst(d, cx, cy, r=38, colour=(255, 220, 120)):
    for angle_deg in range(0, 360, 30):
        a = math.radians(angle_deg)
        x2 = int(cx + r * math.cos(a))
        y2 = int(cy + r * math.sin(a))
        d.line((cx, cy, x2, y2), fill=colour, width=1)


# ---------------------------------------------------------------------------
# Single-frame render
# ---------------------------------------------------------------------------
def _render_image(usage: dict, size: int, frame_idx: int,
                   celebrating: bool) -> Image.Image:
    p5 = usage["five_hour"]["utilization"]
    p7 = usage["seven_day"]["utilization"]

    waving = (not celebrating) and p7 >= 100

    img = Image.new("RGB", (size, size),
                    (24, 12, 40) if celebrating else (12, 16, 40))
    d = ImageDraw.Draw(img)

    # starfield (dimmer during celebration so confetti pops)
    random.seed(7)
    for _ in range(70):
        x, y = random.randint(0, size - 1), random.randint(0, size - 1)
        b = random.choice([50, 90, 140] if celebrating else [80, 140, 210])
        d.point((x, y), fill=(b, b, b))

    # moon / starburst
    mx, my, mr = 188, 62, 34
    if celebrating:
        _draw_starburst(d, mx, my, r=40, colour=(255, 220, 120))
        d.ellipse((mx - mr + 4, my - mr + 4, mx + mr - 4, my + mr - 4),
                  fill=(255, 235, 160))
    else:
        moon_fill   = (220, 90, 80)  if waving else (240, 176, 82)
        moon_crater = (170, 50, 50)  if waving else (200, 140, 60)
        d.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=moon_fill)
        d.ellipse((mx - 10, my - 4,  mx,      my + 6),  fill=moon_crater)
        d.ellipse((mx + 6,  my + 8,  mx + 14, my + 16), fill=moon_crater)

    # header
    d.text((8, 8),  "CLAUDE", font=load_font(9), fill=(230, 230, 230))
    d.text((8, 22), "USAGE",  font=load_font(9), fill=(230, 230, 230))

    # big weekly %
    if   celebrating: pct_colour = (120, 220, 140)
    elif waving:      pct_colour = (255, 90, 90)
    else:             pct_colour = (255, 140, 60)
    d.text((8, 60),  f"{int(round(p7))}%", font=load_font(30), fill=pct_colour)
    d.text((8, 104), "7-DAY", font=load_font(8),  fill=(180, 180, 190))
    d.text((8, 118), f"5H {int(round(p5))}%",
           font=load_font(8), fill=(120, 220, 140))

    # surface bar
    by_ = 202
    d.rectangle((8, by_, size - 8, by_ + 14), outline=(80, 80, 90), width=1)
    fill_w = int((size - 18) * min(p7, 100) / 100)
    if   celebrating: bar_colour = (120, 220, 140)
    elif waving:      bar_colour = (220, 60, 60)
    else:             bar_colour = (255, 140, 60)
    d.rectangle((10, by_ + 2, 10 + fill_w, by_ + 12), fill=bar_colour)
    d.text((8, by_ + 18),         "0",   font=load_font(7), fill=(150, 150, 160))
    d.text((size - 30, by_ + 18), "MAX", font=load_font(7), fill=(150, 150, 160))

    if celebrating:
        _draw_confetti(d, size, frame_idx)

    # Rocky selection & placement
    if   celebrating: sprite = _ROCKY_PARTY[frame_idx % len(_ROCKY_PARTY)]
    elif waving:      sprite = _ROCKY_WAVE [frame_idx % len(_ROCKY_WAVE)]
    else:             sprite = _ROCKY      [frame_idx % len(_ROCKY)]

    sw, sh = sprite.size
    travel = size - 20 - sw
    if celebrating:
        bounce = -2 if (frame_idx % 2) else 0
        rx = 14
        ry = by_ - sh + 2 + bounce
    else:
        rx = 10 + int(travel * min(p7, 100) / 100)
        ry = by_ - sh + 2
    img.paste(sprite, (rx, ry), sprite)

    # Speech bubble
    text, tone = _warning_text(p5, p7)
    if waving:      text, tone = ("HELLO!", "alarm")
    if celebrating: text, tone = ("FRESH!", "party")
    if text:
        anchor_x = rx + sw // 2
        anchor_y = max(46, ry)
        _speech_bubble(d, (anchor_x, anchor_y), text, tone, size)

    return img


def encode_jpeg_frame(img: Image.Image) -> bytes:
    """JPEG-encode with the pinned qtables + 96x96-DPI APP0 some GeekMagic
    firmware requires (see transports/geekmagic.py). Frames from
    render_frames() are plain PIL Images precisely so each transport can
    encode them however its own device needs -- this helper is that
    encoding for the older GeekMagic container transport; the newer
    SmallTV Ultra firmware wants a plain animated GIF instead (see
    transports/smalltv_ultra.py) and has no use for this.
    """
    buf = io.BytesIO()
    img.save(buf, format="JPEG", qtables=[LUMA_QTABLE, CHROMA_QTABLE], subsampling=2)
    frame = buf.getvalue()
    return frame[:2] + APP0_BYTES + frame[20:]


# ---------------------------------------------------------------------------
# Renderer protocol
# ---------------------------------------------------------------------------
def render(five_pct: float, five_reset: str,
           week_pct: float, week_reset: str) -> bytes:
    """Single-frame fallback for the shared Renderer protocol.

    loop.py prefers render_frames() (see below) for real animation; this
    exists so VisualStoryRenderer duck-types as a plain Renderer too. It has
    no access to the raw resets_at timestamp, so it never celebrates.
    """
    usage = {
        "five_hour": {"utilization": five_pct, "resets_at": ""},
        "seven_day": {"utilization": week_pct, "resets_at": ""},
    }
    img = _render_image(usage, size=240, frame_idx=0, celebrating=False)
    return encode_jpeg_frame(img)


def render_frames(usage: dict, size: int = 240, n: int = 33) -> list[Image.Image]:
    """n-frame animation cycle as raw PIL Images.

    Deliberately not encoded here: different transports need different
    on-wire formats (the older GeekMagic container wants pinned-qtable JPEG
    frames, the SmallTV Ultra firmware wants a plain animated GIF), so
    encoding is each transport's job -- see transports/geekmagic.py and
    transports/smalltv_ultra.py.
    """
    celebrating = _is_celebrating(usage)
    return [_render_image(usage, size, i, celebrating) for i in range(n)]


class VisualStoryRenderer:
    """Animated Rocky-the-quota-mascot scene. See render_frames() for the real path."""

    def render(self, five_pct: float, five_reset: str,
               week_pct: float, week_reset: str) -> bytes:
        return render(five_pct, five_reset, week_pct, week_reset)

    def render_frames(self, usage: dict, size: int = 240, n: int = 33) -> list[Image.Image]:
        return render_frames(usage, size, n)
