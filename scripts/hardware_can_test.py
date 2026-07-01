#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hardware smoke test for CAN interface discovery/start/stop/status."""

from __future__ import annotations

import argparse

from hardware_test_common import log, require_confirmation, step
from openflex_driver import (
    disable_can_interface,
    enable_can_interface,
    get_all_can_interfaces,
    verify_can_interface,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenFlex CAN hardware test")
    parser.add_argument("--interfaces", nargs="*", help="CAN interfaces to test. Default: all detected")
    parser.add_argument("--bitrate", type=int, default=1000000)
    parser.add_argument("--driver", default="kcan", choices=["kcan", "peak_usb"])
    parser.add_argument("--start", action="store_true", help="Bring interfaces up before status check")
    parser.add_argument("--stop-after", action="store_true", help="Bring tested interfaces down at the end")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    interfaces = args.interfaces or get_all_can_interfaces()
    if not interfaces:
        log("No CAN interfaces found.")
        return 1

    action = "status check"
    if args.start:
        action = "start + status check"
    if args.stop_after:
        action += " + stop"
    require_confirmation(
        args.yes,
        f"This will run CAN hardware test ({action}) on: {', '.join(interfaces)}.",
    )

    if args.start:
        for iface in interfaces:
            step(
                f"start {iface}",
                lambda i=iface: enable_can_interface(
                    i, bitrate=args.bitrate, driver=args.driver, verbose=True
                ),
            )

    ok = True
    for iface in interfaces:
        is_up = step(f"check {iface}", lambda i=iface: verify_can_interface(i))
        log(f"{iface}: {'UP' if is_up else 'DOWN'}")
        ok = ok and bool(is_up)

    if args.stop_after:
        for iface in interfaces:
            step(f"stop {iface}", lambda i=iface: disable_can_interface(i, verbose=True))

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
