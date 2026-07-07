"""Renderers produce a displayable asset from usage percentages."""
from __future__ import annotations

from typing import Protocol

from PIL import ImageFont

# Shared palette
COLOR_BG     = (0, 0, 0)
COLOR_TEXT   = (235, 235, 235)
COLOR_DIM    = (140, 140, 140)
COLOR_TRACK  = (40, 40, 40)
COLOR_GREEN  = (26, 166, 75)
COLOR_YELLOW = (228, 184, 26)
COLOR_RED    = (217, 58, 58)


def bar_color(pct: float):
    if pct >= 90:
        return COLOR_RED
    if pct >= 70:
        return COLOR_YELLOW
    return COLOR_GREEN


def load_font(size: int) -> ImageFont.ImageFont:
    for path in [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


class Renderer(Protocol):
    """A Renderer turns usage percentages into bytes for a transport."""

    def render(self, five_pct: float, five_reset: str,
               week_pct: float, week_reset: str) -> bytes: ...


def get(mode: str) -> Renderer:
    """Factory: resolve a mode name to a Renderer instance."""
    if mode == "gif80":
        from claude_meter.renderers.gif80 import Gif80Renderer
        return Gif80Renderer()
    if mode == "photo240":
        from claude_meter.renderers.photo240 import Photo240Renderer
        return Photo240Renderer()
    if mode == "visual_story":
        from claude_meter.renderers.visual_story import VisualStoryRenderer
        return VisualStoryRenderer()
    raise ValueError(
        f"unknown render mode: {mode!r} (expected 'gif80', 'photo240', or 'visual_story')"
    )
