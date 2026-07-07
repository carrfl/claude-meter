"""claude-meter command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from claude_meter import __version__, config, loop, service
from claude_meter.auth import AuthError, get_access_token
from claude_meter.usage import fetch_usage


def _cmd_run(_args) -> int:
    cfg = config.load()
    loop.run(cfg)
    return 0


def _cmd_configure(args) -> int:
    cfg = config.load()
    if args.device_host:
        cfg.device_host = args.device_host
    if args.mode:
        cfg.mode = args.mode
    if args.transport:
        cfg.transport = args.transport
    if args.push_interval is not None:
        cfg.push_interval_sec = args.push_interval
    if args.force_push is not None:
        cfg.force_push_sec = args.force_push
    p = config.save(cfg)
    print(f"wrote {p}")
    print(json.dumps(asdict(cfg), indent=2))
    return 0


def _cmd_show(_args) -> int:
    cfg = config.load()
    print(f"# {config.config_path()}")
    print(json.dumps(asdict(cfg), indent=2))
    return 0


def _cmd_check(_args) -> int:
    """Verify auth + API + device reachability without looping."""
    try:
        _, org = get_access_token()
        print(f"auth:   ok (org={org})")
    except AuthError as e:
        print(f"auth:   FAIL — {e}", file=sys.stderr)
        return 2

    try:
        data = fetch_usage()
        five = (data.get("five_hour") or {}).get("utilization")
        week = (data.get("seven_day") or {}).get("utilization")
        print(f"usage:  ok (5h={five}%, 7d={week}%)")
    except Exception as e:
        print(f"usage:  FAIL — {e}", file=sys.stderr)
        return 2

    cfg = config.load()
    print(f"config: {config.config_path()}")
    print(f"        device={cfg.device_host} mode={cfg.mode} "
          f"interval={cfg.push_interval_sec}s")
    return 0


def _cmd_install_service(_args) -> int:
    path = service.install()
    print(f"installed {path}")
    return 0


def _cmd_uninstall_service(_args) -> int:
    path = service.uninstall()
    if path is None:
        print("no service installed")
    else:
        print(f"removed {path}")
    return 0


def _cmd_status(_args) -> int:
    print(service.status())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-meter",
        description="Push Claude Code usage to a tiny screen.",
    )
    p.add_argument("--version", action="version", version=f"claude-meter {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run",   help="Run the push loop in the foreground").set_defaults(
        func=_cmd_run)
    sub.add_parser("check", help="Verify auth + API + config").set_defaults(
        func=_cmd_check)
    sub.add_parser("show",  help="Print the current config").set_defaults(
        func=_cmd_show)

    pc = sub.add_parser("configure", help="Update config values")
    pc.add_argument("--device-host",   help="IP or hostname of the clock, e.g. 192.168.1.50")
    pc.add_argument("--mode",          choices=["gif80", "photo240", "visual_story"])
    pc.add_argument("--transport",     choices=["geekmagic", "smalltv_ultra"])
    pc.add_argument("--push-interval", type=int, dest="push_interval",
                    help="seconds between pushes (default 60)")
    pc.add_argument("--force-push",    type=int, dest="force_push",
                    help="seconds between re-pushes of unchanged values (default 600)")
    pc.set_defaults(func=_cmd_configure)

    sub.add_parser("install-service",
                   help="Install as launchd/systemd user service").set_defaults(
        func=_cmd_install_service)
    sub.add_parser("uninstall-service",
                   help="Remove the installed service").set_defaults(
        func=_cmd_uninstall_service)
    sub.add_parser("service-status",
                   help="Show status of the installed service").set_defaults(
        func=_cmd_status)

    return p


def main() -> None:
    args = build_parser().parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
