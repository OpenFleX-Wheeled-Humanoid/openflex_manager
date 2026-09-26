#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hardware smoke test for OpenFlex head yaw/pitch motors."""

from __future__ import annotations

import argparse
import math

from hardware_test_common import print_status, require_confirmation, step, wait_seconds
from openflex_driver.head import Head, JOINT_PITCH, JOINT_YAW


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenFlex head hardware motion test")
    parser.add_argument("--can", default="can2")
    parser.add_argument("--motor-id", type=int, choices=[JOINT_YAW, JOINT_PITCH], default=JOINT_YAW)
    parser.add_argument("--both", action="store_true", help="Test yaw and pitch")
    parser.add_argument("--step-deg", type=float, default=3.0)
    parser.add_argument("--hold", type=float, default=0.8)
    parser.add_argument("--kp-percent", type=float, default=20.0)
    parser.add_argument("--kd-percent", type=float, default=100.0)
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def test_joint(head: Head, motor_id: int, step_deg: float, hold: float) -> int:
    status = step(f"read head motor {motor_id} status", lambda: head.get_motor_status(motor_id))
    if not status:
        raise RuntimeError(f"No feedback from head motor {motor_id}")
    print_status(f"initial motor {motor_id}", status)

    start_logical = head.to_logical_angle(motor_id, float(status.get("angle", 0.0)))
    target = start_logical + math.radians(step_deg)
    step(
        f"move head motor {motor_id} by {step_deg:.2f} deg",
        lambda: head.move_to_mit(motor_id=motor_id, position=target, wait_response=False, verbose=True),
    )
    wait_seconds(hold, "observe head motion")
    step(
        f"return head motor {motor_id}",
        lambda: head.move_to_mit(motor_id=motor_id, position=start_logical, wait_response=False, verbose=True),
    )
    wait_seconds(hold, "return motion")
    final = step(f"read final head motor {motor_id} status", lambda: head.get_motor_status(motor_id))
    print_status(f"final motor {motor_id}", final)
    return 0


def main() -> int:
    args = parse_args()
    motor_ids = [JOINT_YAW, JOINT_PITCH] if args.both else [args.motor_id]
    require_confirmation(
        args.yes,
        f"This will move head motor(s) {motor_ids} on {args.can} by {args.step_deg} deg. "
        "Make sure the head can move freely.",
    )

    head = Head(
        can_channel=args.can,
        auto_enable_can=False,
        log=lambda msg, level="INFO": print(f"[{level}] {msg}"),
    )
    try:
        step("connect head", head.connect)
        head.set_kp_kd_percent(args.kp_percent, args.kd_percent)
        results = step("enable head motors", lambda: head.enable(verbose=True))
        print_status("enable results", results)
        if any(results.get(mid, 1) != 0 for mid in motor_ids):
            raise RuntimeError("Selected head motor did not enable successfully")
        for mid in motor_ids:
            test_joint(head, mid, args.step_deg, args.hold)
        return 0
    finally:
        try:
            head.disable(verbose=True)
        finally:
            head.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
