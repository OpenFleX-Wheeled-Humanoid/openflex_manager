#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hardware smoke test for OpenFlex chassis steering and drive modules."""

from __future__ import annotations

import argparse

from hardware_test_common import print_status, require_confirmation, step, wait_seconds
from openflex_driver.chassis import Chassis, MODULE_NAMES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenFlex chassis hardware motion test")
    parser.add_argument("--steering-can", default="can5")
    parser.add_argument("--driving-can", default="can4")
    parser.add_argument("--module", choices=list(MODULE_NAMES), default="FL")
    parser.add_argument("--all-modules", action="store_true", help="Enable/test all modules")
    parser.add_argument("--steer-deg", type=float, default=5.0)
    parser.add_argument("--drive-rpm", type=float, default=20.0)
    parser.add_argument("--drive-time", type=float, default=0.8)
    parser.add_argument("--whole-body", action="store_true", help="Also run short forward/backward chassis motion")
    parser.add_argument("--linear-speed", type=float, default=0.05, help="m/s")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def test_module(chassis: Chassis, module: str, steer_deg: float, drive_rpm: float, drive_time: float) -> None:
    step(f"enable module {module}", lambda: chassis.enable_module(module))
    current = step(f"read {module} steering angle", lambda: chassis.read_module_steering_angle_deg(module))
    print_status(f"{module} steering angle", current)
    target = (float(current) if current is not None else 0.0) + steer_deg
    step(f"steer {module} to {target:.2f} deg", lambda: chassis.set_steering_angle_deg(module, target))
    wait_seconds(0.5, "observe steering")
    step(f"steer {module} back", lambda: chassis.set_steering_angle_deg(module, float(current) if current is not None else 0.0))
    wait_seconds(0.5)
    step(f"drive {module} at {drive_rpm:.1f} RPM", lambda: chassis.set_driving_speed_rpm(module, drive_rpm))
    wait_seconds(drive_time, "observe wheel rotation")
    step(f"stop {module} drive", lambda: chassis.stop_module_driving(module))


def main() -> int:
    args = parse_args()
    modules = list(MODULE_NAMES) if args.all_modules else [args.module]
    require_confirmation(
        args.yes,
        f"This will move chassis module(s) {modules}. Steering={args.steer_deg}deg, "
        f"drive={args.drive_rpm}RPM for {args.drive_time}s. Lift wheels or clear the floor area.",
    )

    chassis = Chassis(
        steering_can=args.steering_can,
        driving_can=args.driving_can,
        log=lambda msg, level="INFO": print(f"[{level}] {msg}"),
    )
    try:
        step("connect chassis", chassis.connect)
        scan = step("scan chassis motors", chassis.scan_motors)
        print_status("scan results", scan)

        for module in modules:
            test_module(chassis, module, args.steer_deg, args.drive_rpm, args.drive_time)

        if args.whole_body:
            step("enable all chassis motors", lambda: chassis.enable_all_motors(verbose=True))
            step(f"move forward {args.linear_speed:.3f} m/s", lambda: chassis.move_forward(args.linear_speed))
            wait_seconds(args.drive_time, "observe forward motion")
            step("stop chassis", chassis.stop_all_driving)
            step(f"move backward {args.linear_speed:.3f} m/s", lambda: chassis.move_backward(args.linear_speed))
            wait_seconds(args.drive_time, "observe backward motion")
            step("stop chassis", chassis.stop_all_driving)

        return 0
    finally:
        try:
            chassis.stop_all_driving()
        except Exception:
            pass
        chassis.close()


if __name__ == "__main__":
    raise SystemExit(main())
