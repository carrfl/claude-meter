"""Transports deliver rendered bytes to a physical display."""
from __future__ import annotations

from typing import Protocol


class Transport(Protocol):
    """Push rendered bytes (or, for animated renderers, a list of per-frame
    bytes) somewhere visible."""

    def push(self, payload: bytes | list[bytes]) -> int:
        """Send the payload. Return bytes-on-wire for logging."""


def get(name: str, **kwargs) -> Transport:
    if name == "geekmagic":
        from claude_meter.transports.geekmagic import GeekmagicTransport
        return GeekmagicTransport(**kwargs)
    if name == "smalltv_ultra":
        from claude_meter.transports.smalltv_ultra import SmallTVUltraTransport
        return SmallTVUltraTransport(**kwargs)
    raise ValueError(f"unknown transport: {name!r}")
