"""Config file discovery + schema.

Stored as JSON at (in order of preference):
  $CLAUDE_METER_CONFIG                    (explicit override)
  $XDG_CONFIG_HOME/claude-meter/config.json
  ~/.config/claude-meter/config.json      (both macOS and Linux)
"""
from __future__ import annotations

import json
import os
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Config:
    device_host: str = ""
    mode:        str = "gif80"          # gif80 | photo240 | visual_story
    transport:   str = "geekmagic"      # geekmagic | smalltv_ultra
    push_interval_sec: int = 60
    force_push_sec:    int = 600

    @classmethod
    def defaults(cls) -> "Config":
        return cls()


def config_path() -> pathlib.Path:
    override = os.environ.get("CLAUDE_METER_CONFIG")
    if override:
        return pathlib.Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = pathlib.Path(xdg).expanduser() if xdg else pathlib.Path.home() / ".config"
    return base / "claude-meter" / "config.json"


def load(path: Optional[pathlib.Path] = None) -> Config:
    p = path or config_path()
    if not p.exists():
        return Config.defaults()
    try:
        data = json.loads(p.read_text())
    except Exception as e:
        raise RuntimeError(f"{p}: {e}") from e
    cfg = Config.defaults()
    # Only copy keys that exist on the dataclass, so unknown keys are ignored.
    valid = set(cfg.__dataclass_fields__.keys())
    for k, v in data.items():
        if k in valid:
            setattr(cfg, k, v)
    return cfg


def save(cfg: Config, path: Optional[pathlib.Path] = None) -> pathlib.Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    return p
