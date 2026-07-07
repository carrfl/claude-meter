"""Push loop: fetch usage, render, push, dedup, sleep."""
from __future__ import annotations

import datetime
import json
import sys
import time

from claude_meter import renderers, transports
from claude_meter.config import Config
from claude_meter.usage import RateLimited, extract, fetch_usage


def run(cfg: Config) -> None:
    if not cfg.device_host:
        raise SystemExit(
            "device_host is not set. Run `claude-meter configure "
            "--device-host <ip>` first."
        )
    renderer  = renderers.get(cfg.mode)
    transport = transports.get(cfg.transport, host=cfg.device_host, mode=cfg.mode)

    logged_once  = False
    last_key:   tuple | None = None
    last_push_ts = 0.0
    fail_streak  = 0

    while True:
        sleep_for = cfg.push_interval_sec
        try:
            data = fetch_usage()
            if not logged_once:
                print("API response:", json.dumps(data, indent=2), flush=True)
                logged_once = True

            five_pct, five_reset, week_pct, week_reset = extract(data)
            key = (int(round(five_pct)), int(round(week_pct)))
            now = time.time()

            if last_key == key and (now - last_push_ts) < cfg.force_push_sec:
                print(f"{_ts()} 5h {five_pct:.0f}%  7d {week_pct:.0f}%  "
                      f"unchanged, skipped", flush=True)
            else:
                if hasattr(renderer, "render_frames"):
                    # Animated renderer (e.g. visual_story): needs the raw
                    # usage dict (resets_at, etc.), not the pre-formatted
                    # display strings the plain Renderer protocol gets.
                    payload = renderer.render_frames(data)
                else:
                    payload = renderer.render(five_pct, five_reset, week_pct, week_reset)
                n = transport.push(payload)
                last_key     = key
                last_push_ts = now
                print(f"{_ts()} 5h {five_pct:.0f}%  7d {week_pct:.0f}%  "
                      f"pushed {n}B ({cfg.mode})", flush=True)
            fail_streak = 0
        except KeyboardInterrupt:
            print("bye", flush=True)
            sys.exit(0)
        except RateLimited as e:
            sleep_for = max(e.retry_after, cfg.push_interval_sec)
            print(f"{_ts()} [warn] 429 rate limited, sleeping {sleep_for}s",
                  flush=True)
        except Exception as e:
            fail_streak += 1
            sleep_for = min(cfg.push_interval_sec * (2 ** (fail_streak - 1)), 600)
            print(f"{_ts()} [warn] {type(e).__name__}: {e} "
                  f"(retry in {sleep_for}s)", flush=True)

        time.sleep(sleep_for)


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")
