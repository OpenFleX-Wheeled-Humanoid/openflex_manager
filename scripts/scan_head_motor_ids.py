#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scan head motor IDs by reusing the same openarmx_arm_driver.Arm path used by
check_motor_status.py.

The wide ID scan is isolated one ID per subprocess. This avoids a full scan
being killed when the openarmx_arm_driver binary layer crashes on an unknown
or incompatible ID.
"""

import argparse
import json
import subprocess
import sys
import time


RESULT_PREFIX = "OPENFLEX_SCAN_RESULT "


def is_can_up(channel: str) -> bool:
    result = subprocess.run(
        ["ip", "link", "show", channel],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    flags = first_line.split(">", 1)[0]
    return "state UP" in first_line or ("<" in flags and "UP" in flags)


def _internal_scan_one(can_channel: str, motor_id: int, timeout: float, bitrate: int) -> int:
    try:
        from openarmx_arm_driver import Arm
    except ImportError as exc:
        print(
            RESULT_PREFIX + json.dumps(
                {"ok": False, "error": f"import openarmx_arm_driver failed: {exc}"},
                ensure_ascii=False,
            )
        )
        return 2

    arm = None
    try:
        arm = Arm(
            can_channel=can_channel,
            side="right",
            motor_ids=[motor_id],
            bitrate=bitrate,
            auto_enable_can=False,
        )
        info = arm.get_status(motor_id, timeout=timeout, verbose=False)
        if info:
            print(
                RESULT_PREFIX + json.dumps(
                    {
                        "ok": True,
                        "id": motor_id,
                        "angle": info.get("angle"),
                        "velocity": info.get("velocity"),
                        "torque": info.get("torque"),
                        "temperature": info.get("temperature"),
                        "mode_status": info.get("mode_status"),
                        "fault_status": info.get("fault_status"),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        print(RESULT_PREFIX + json.dumps({"ok": False, "id": motor_id}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(
            RESULT_PREFIX + json.dumps(
                {"ok": False, "id": motor_id, "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    finally:
        if arm is not None:
            try:
                arm.close()
            except Exception:
                pass


def parse_internal_result(output: str):
    for line in reversed(output.splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                return json.loads(line[len(RESULT_PREFIX):])
            except json.JSONDecodeError:
                return {"ok": False, "error": "bad child result json"}
    return {"ok": False, "error": "no child result"}


def scan_one(script_path: str, args, motor_id: int):
    cmd = [
        sys.executable,
        script_path,
        "--_scan-one",
        "--can",
        args.can,
        "--id",
        str(motor_id),
        "--timeout",
        str(args.timeout),
        "--bitrate",
        str(args.bitrate),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode < 0:
        return {
            "ok": False,
            "id": motor_id,
            "crashed": True,
            "error": f"child process terminated by signal {-result.returncode}",
        }

    data = parse_internal_result(result.stdout)
    data.setdefault("id", motor_id)
    if args.verbose and (result.stderr or result.stdout):
        data["stdout"] = result.stdout.strip()
        data["stderr"] = result.stderr.strip()
    return data


def format_value(value, digits=3):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan head motor IDs using the same Arm API as check_motor_status.py."
    )
    parser.add_argument("--can", default="can5", help="CAN channel, default: can5")
    parser.add_argument("--start", type=int, default=125, help="Start ID, default: 125")
    parser.add_argument("--end", type=int, default=127, help="End ID, default: 127")
    parser.add_argument("--timeout", type=float, default=0.25, help="Timeout per ID in seconds")
    parser.add_argument("--bitrate", type=int, default=1000000, help="CAN bitrate, default: 1000000")
    parser.add_argument("--sleep", type=float, default=0.02, help="Delay between IDs in seconds")
    parser.add_argument("--verbose", action="store_true", help="Print child process errors")

    parser.add_argument("--_scan-one", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--id", type=int, help=argparse.SUPPRESS)
    return parser.parse_args()


def main():
    args = parse_args()

    if args._scan_one:
        if args.id is None:
            print(RESULT_PREFIX + json.dumps({"ok": False, "error": "missing --id"}))
            return 2
        return _internal_scan_one(args.can, args.id, args.timeout, args.bitrate)

    if args.start < 1 or args.end > 127 or args.start > args.end:
        print("ERROR: ID range must satisfy 1 <= start <= end <= 127", file=sys.stderr)
        return 2

    print("=" * 72)
    print("OpenFlex head motor ID scan")
    print("=" * 72)
    print(f"CAN channel : {args.can}")
    print(f"ID range    : {args.start}-{args.end}")
    print(f"Timeout     : {args.timeout:.3f}s per ID")
    print("Mode        : openarmx_arm_driver.Arm, isolated per ID")
    print("-" * 72)

    if not is_can_up(args.can):
        print(f"ERROR: {args.can} is not UP. Please enable the CAN interface first.")
        return 1

    script_path = __file__
    found = []
    crashed = []
    progress_printed = False

    print(f"{'ID':<5} {'OK':<4} {'Angle(rad)':<12} {'Vel(rad/s)':<12} "
          f"{'Torque':<10} {'Temp':<8} {'Mode/Fault'}")
    print("-" * 72)

    for motor_id in range(args.start, args.end + 1):
        data = scan_one(script_path, args, motor_id)
        if data.get("ok"):
            if progress_printed:
                print("\r" + " " * 72 + "\r", end="", flush=True)
                progress_printed = False
            found.append(motor_id)
            print(
                f"{motor_id:<5} {'YES':<4} "
                f"{format_value(data.get('angle')):<12} "
                f"{format_value(data.get('velocity')):<12} "
                f"{format_value(data.get('torque')):<10} "
                f"{format_value(data.get('temperature'), 1):<8} "
                f"{data.get('mode_status', '-')}/{data.get('fault_status', '-')}"
            )
        else:
            if data.get("crashed"):
                crashed.append(motor_id)
                if args.verbose:
                    print(f"\nID {motor_id}: {data.get('error')}")
            elif args.verbose and data.get("error"):
                print(f"\nID {motor_id}: {data.get('error')}")
            print(f"\rScanning ID {motor_id:3d}/{args.end} ...", end="", flush=True)
            progress_printed = True

        if args.sleep > 0:
            time.sleep(args.sleep)

    if progress_printed:
        print()
    print("-" * 72)
    if found:
        print(f"Found {len(found)} responsive motor ID(s): {found}")
    else:
        print("No responsive motor IDs found.")
    if crashed:
        print(f"IDs that crashed the child scan process: {crashed}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
