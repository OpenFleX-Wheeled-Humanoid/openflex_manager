#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hardware smoke test for OpenFlex lift column."""

from __future__ import annotations

import argparse
import time

from hardware_test_common import print_status, require_confirmation, step, wait_seconds
from openflex_driver.column import Column, CONTROL_MODE_POSITION, CONTROL_MODE_VELOCITY


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenFlex lift column hardware motion test")
    parser.add_argument("--can", default="can3")
    parser.add_argument("--node-id", type=int, default=16)
    parser.add_argument("--jog-speed", type=float, default=0.01, help="m/s")
    parser.add_argument("--jog-time", type=float, default=0.8, help="seconds")
    parser.add_argument("--move-delta", type=float, default=0.01, help="relative position move in meters")
    parser.add_argument("--skip-jog", action="store_true")
    parser.add_argument("--skip-position", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def poll_status(column: Column, title: str) -> dict:
    step("refresh column status", column.refresh_status)
    status = column.get_status()
    print_status(title, status)
    return status


def main() -> int:
    args = parse_args()
    require_confirmation(
        args.yes,
        f"This will move lift column node {args.node_id} on {args.can}. "
        f"Jog speed={args.jog_speed}m/s, position delta={args.move_delta}m. "
        "Make sure the lift path is clear.",
    )

    column = Column(can_interface=args.can, node_id=args.node_id, log=lambda msg, level="INFO": print(f"[{level}] {msg}"))
    try:
        step("connect column", column.connect)
        step("enable column", column.enable)
        poll_status(column, "initial")

        if not args.skip_jog:
            step("switch to velocity mode", column.switch_to_velocity_mode)
            if column.get_control_mode() != CONTROL_MODE_VELOCITY:
                raise RuntimeError("Column did not enter velocity mode")
            step(f"jog up at {args.jog_speed:.4f} m/s", lambda: column.jog_velocity(abs(args.jog_speed)))
            wait_seconds(args.jog_time, "observe upward jog")
            step("stop jog", lambda: column.jog_velocity(0.0))
            wait_seconds(0.2)
            step(f"jog down at {args.jog_speed:.4f} m/s", lambda: column.jog_velocity(-abs(args.jog_speed)))
            wait_seconds(args.jog_time, "observe downward jog")
            step("stop jog", lambda: column.jog_velocity(0.0))
            poll_status(column, "after jog")

        if not args.skip_position:
            status = poll_status(column, "before position move")
            current = float(status.get("position_m", 0.0))
            target = current + float(args.move_delta)
            target = max(column.min_position_m, min(column.max_position_m, target))
            step("switch to position mode", column.switch_to_position_mode)
            if column.get_control_mode() != CONTROL_MODE_POSITION:
                raise RuntimeError("Column did not enter position mode")
            step(f"move to {target:.4f} m", lambda: column.move_to_user_position(target, speed_mps=max(abs(args.jog_speed), 0.005)))
            time.sleep(0.3)
            step(f"return to {current:.4f} m", lambda: column.move_to_user_position(current, speed_mps=max(abs(args.jog_speed), 0.005)))
            poll_status(column, "after position move")

        return 0
    finally:
        try:
            column.stop_motion()
        except Exception:
            pass
        try:
            column.disable()
        except Exception:
            pass
        column.close()


if __name__ == "__main__":
    raise SystemExit(main())
