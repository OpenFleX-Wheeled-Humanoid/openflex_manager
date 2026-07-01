#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for OpenFlex hardware smoke tests."""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Callable


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def log(message: str) -> None:
    print(message, flush=True)


def require_confirmation(yes: bool, message: str) -> None:
    if yes:
        return
    log("")
    log(message)
    answer = input("Type YES to continue: ").strip()
    if answer != "YES":
        raise SystemExit("Aborted by user.")


def step(name: str, fn: Callable[[], Any]) -> Any:
    log(f"\n[STEP] {name}")
    try:
        result = fn()
    except Exception as exc:
        log(f"[FAIL] {name}: {exc}")
        raise
    log(f"[ OK ] {name}")
    return result


def wait_seconds(seconds: float, reason: str = "") -> None:
    if seconds <= 0:
        return
    suffix = f" ({reason})" if reason else ""
    log(f"Waiting {seconds:.2f}s{suffix}...")
    time.sleep(seconds)


def print_status(title: str, status: Any) -> None:
    log(f"\n{title}:")
    log(str(status))
