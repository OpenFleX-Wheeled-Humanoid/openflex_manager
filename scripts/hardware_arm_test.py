#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hardware smoke test for one OpenFlex arm motor or all arm motors."""

from __future__ import annotations

import argparse
import math

from hardware_test_common import print_status, require_confirmation, step, wait_seconds
from openflex_driver import Arm


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenFlex arm hardware motion test")
    parser.add_argument("--can", default="can0", help="Arm CAN interface")
    parser.add_argument("--side", default="right", choices=["right", "left", "none"])
    parser.add_argument("--motor-id", type=int, default=1, help="Motor ID to move")
    parser.add_argument("--all", action="store_true", help="Run built-in one-by-one test on all 8 motors")
    parser.add_argument("--step-deg", type=float, default=3.0, help="Small relative motion in degrees")
    parser.add_argument("--hold", type=float, default=0.8, help="Hold time at target")
    parser.add_argument("--kp", type=float, default=10.0)
    parser.add_argument("--kd", type=float, default=1.0)
    parser.add_argument("--driver", default="kcan", choices=["kcan", "peak_usb"])
    parser.add_argument("--auto-enable-can", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    side = None if args.side == "none" else args.side
    target_desc = "all 8 motors one by one" if args.all else f"motor {args.motor_id}"
    require_confirmation(
        args.yes,
        f"This will move arm {target_desc} on {args.can} by a small amount. "
        "Make sure the arm workspace is clear and emergency stop is reachable.",
    )

    arm = Arm(
        args.can,
        side=side,
        auto_enable_can=args.auto_enable_can,
        driver=args.driver,
        log=lambda msg, level="INFO": print(f"[{level}] {msg}"),
    )
    try:
        if args.all:
            positions = [math.radians(args.step_deg)] * 8
            results = step(
                "test all arm motors one by one",
                lambda: arm.test_motors_one_by_one(
                    positions=positions,
                    kp=args.kp,
                    kd=args.kd,
                    duration=args.hold,
                    verbose=True,
                ),
            )
            print_status("results", results)
            return 0 if all(v == 0 for v in results.values()) else 2

        status = step("read initial motor status", lambda: arm.get_motor_status(args.motor_id))
        if not status:
            raise RuntimeError(f"No feedback from motor {args.motor_id}")
        print_status("initial", status)
        start_rad = float(status.get("angle", 0.0))
        target_rad = start_rad + math.radians(args.step_deg)

        step("enable motor", lambda: arm.enable_arm_motors(args.motor_id, verbose=True))
        step(
            f"move motor {args.motor_id} to {math.degrees(target_rad):.2f} deg",
            lambda: arm.move_to_mit(
                motor_id=args.motor_id,
                position=target_rad,
                kp=args.kp,
                kd=args.kd,
                wait_response=False,
                verbose=True,
            ),
        )
        wait_seconds(args.hold, "observe motion")
        step(
            f"return motor {args.motor_id} to start",
            lambda: arm.move_to_mit(
                motor_id=args.motor_id,
                position=start_rad,
                kp=args.kp,
                kd=args.kd,
                wait_response=False,
                verbose=True,
            ),
        )
        wait_seconds(args.hold, "return motion")
        final = step("read final motor status", lambda: arm.get_motor_status(args.motor_id))
        print_status("final", final)
        return 0
    finally:
        try:
            arm.disable_arm_motors(args.motor_id if not args.all else None, verbose=True)
        finally:
            arm.bus.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
