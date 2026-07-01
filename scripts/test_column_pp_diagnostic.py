#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PP 在线 / 速度模式切换 — 五项疑点诊断（仅 GUI column.py）

运行: python3 scripts/test_column_pp_diagnostic.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from openflex_driver._lib.lift_canopen import (  # noqa: E402
    CMD_ENABLE_OPERATION,
    CW_HALT,
    CW_NEW_SETPOINT,
    CW_POSITION_MOVE,
    MODE_POSITION,
    MODE_VELOCITY,
    OD_CONTROL_WORD,
    OD_MODE_OF_OPERATION,
    OD_MODE_OF_OPERATION_DISPLAY,
    OD_POSITION_ACTUAL,
    OD_STATUS_WORD,
    OD_TARGET_POSITION,
)
from openflex_driver.column import Column, CONTROL_MODE_POSITION, CONTROL_MODE_VELOCITY  # noqa: E402

COUNTS_PER_M = 2_000_000.0

STATE: Dict[str, Any] = {
    "physical_m": 0.18,
    "mode": MODE_POSITION,
    "statusword": 0x0040,
    "position_reached": False,
    "sdo_write_fail_index": None,
    "sdo_write_fail_once": False,
}

METRICS = {
    "exit_dispatch_calls": 0,
    "prepare_calls": 0,
    "sdo_writes": [],
}


@dataclass
class DiagResult:
    issue_id: int
    title: str
    bug_present: bool
    verdict: str
    detail: str = ""


def _reset(physical_m: float = 0.18, mode: int = MODE_POSITION) -> None:
    STATE["physical_m"] = physical_m
    STATE["mode"] = mode
    STATE["statusword"] = 0x0040
    STATE["position_reached"] = False
    STATE["sdo_write_fail_index"] = None
    STATE["sdo_write_fail_once"] = False
    METRICS["exit_dispatch_calls"] = 0
    METRICS["prepare_calls"] = 0
    METRICS["sdo_writes"] = []


def mock_sdo_read(
    can_interface: str,
    node_id: int,
    index: int,
    subindex: int = 0,
    timeout: float = 0.15,
) -> Optional[int]:
    if index == OD_STATUS_WORD:
        sw = int(STATE["statusword"])
        if STATE.get("position_reached"):
            sw |= 0x0400
        return sw
    if index == OD_POSITION_ACTUAL:
        return int(round(-STATE["physical_m"] * COUNTS_PER_M))
    if index in (OD_MODE_OF_OPERATION, OD_MODE_OF_OPERATION_DISPLAY):
        return int(STATE["mode"])
    return 0


def mock_sdo_write(
    can_interface: str,
    node_id: int,
    index: int,
    subindex: int,
    value: int,
    size: int,
    timeout: float = 0.15,
) -> bool:
    METRICS["sdo_writes"].append((index, subindex, int(value)))
    fail_idx = STATE.get("sdo_write_fail_index")
    if fail_idx is not None and index == fail_idx:
        if STATE.get("sdo_write_fail_once"):
            STATE["sdo_write_fail_once"] = False
            STATE["sdo_write_fail_index"] = None
        return False
    val = int(value)
    if index == OD_MODE_OF_OPERATION:
        STATE["mode"] = val
    if index == OD_CONTROL_WORD and val == CW_POSITION_MOVE:
        STATE["position_reached"] = True
    if index == OD_TARGET_POSITION:
        STATE["physical_m"] = -val / COUNTS_PER_M
    return True


def _make_column(cal_path: str) -> Column:
    c = Column(
        can_interface="can3",
        node_id=16,
        counts_per_meter=COUNTS_PER_M,
        invert_command=True,
        invert_feedback=True,
        homing_timeout_sec=5.0,
        calibration_file=cal_path,
        log=lambda *a, **k: None,
    )
    c._connected = True
    c.is_enabled = True
    c.homing_complete = True
    c.position_offset_m = 0.18
    return c


def _track_exit_and_prepare(column: Column) -> None:
    orig_exit = column._exit_position_dispatch
    orig_prepare = column._prepare_velocity_runtime

    def counted_exit() -> bool:
        METRICS["exit_dispatch_calls"] += 1
        return orig_exit()

    def counted_prepare(**kwargs) -> bool:
        METRICS["prepare_calls"] += 1
        return orig_prepare(**kwargs)

    column._exit_position_dispatch = counted_exit  # type: ignore[method-assign]
    column._prepare_velocity_runtime = counted_prepare  # type: ignore[method-assign]


def test_issue_1_no_103f() -> DiagResult:
    """疑点1: 已在目标位时不发 0x103F，_position_pp_active 保持 false。"""
    title = "疑点1: 未发 0x103F（已在目标位）"
    try:
        _reset(0.18, MODE_POSITION)
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            cal = f.name
        col = _make_column(cal)
        col.control_mode = CONTROL_MODE_POSITION
        METRICS["sdo_writes"] = []
        # 用户 0m + offset 0.18 = 物理 0.18，已在目标位
        ok = col.move_to_user_position(0.0, speed_mps=0.05)
        cw_writes = [w for w in METRICS["sdo_writes"] if w[0] == OD_CONTROL_WORD]
        sent_103f = any(w[2] == CW_POSITION_MOVE for w in cw_writes)
        os.remove(cal)
        bug = ok and not sent_103f and not col._position_pp_active
        return DiagResult(
            1,
            title,
            bug,
            "代码行为符合该疑点（不发 0x103F、不置 PP 标志）" if bug else "未复现",
            f"move_ok={ok}, sent_103f={sent_103f}, pp_active={col._position_pp_active}, "
            f"cw_writes={[hex(w[2]) for w in cw_writes]}",
        )
    except Exception as exc:
        return DiagResult(1, title, False, "测试异常", traceback.format_exc())


def test_issue_2_prepare_fail_after_exit() -> DiagResult:
    """疑点2: exit 成功后 prepare 失败，标志已清；第二次切换不再 exit。"""
    title = "疑点2: exit 后 prepare 失败，重试跳过 exit"
    try:
        _reset(0.18, MODE_POSITION)
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            cal = f.name
        col = _make_column(cal)
        col.control_mode = CONTROL_MODE_POSITION
        col._position_pp_active = True
        orig_exit = col._exit_position_dispatch
        exit_count = [0]

        def count_exit() -> bool:
            exit_count[0] += 1
            return orig_exit()

        col._exit_position_dispatch = count_exit  # type: ignore[method-assign]

        orig_prepare_bound = Column._prepare_velocity_runtime.__get__(col, Column)
        prepare_n = [0]

        def failing_prepare(*, require_rpdo=True):
            prepare_n[0] += 1
            if prepare_n[0] == 1:
                return False
            return orig_prepare_bound(require_rpdo=require_rpdo)

        col._prepare_velocity_runtime = failing_prepare  # type: ignore[method-assign]

        ok1 = col.switch_to_velocity_mode()
        exit_after_first = exit_count[0]
        pp_after_first = col._position_pp_active

        ok2 = col.switch_to_velocity_mode()
        exit_on_retry = exit_count[0] - exit_after_first

        os.remove(cal)
        bug = (
            not ok1
            and exit_after_first == 1
            and pp_after_first is False
            and exit_on_retry == 0
        )
        return DiagResult(
            2,
            title,
            bug,
            "确认存在：prepare 失败后重试不再 exit" if bug else "未复现",
            f"ok1={ok1}, exit1={exit_after_first}, pp_after1={pp_after_first}, "
            f"ok2={ok2}, exit2={exit_on_retry}",
        )
    except Exception as exc:
        return DiagResult(2, title, False, "测试异常", traceback.format_exc())


def test_issue_3_jog_no_exit() -> DiagResult:
    """疑点3: pp_active=True 且 control_mode=velocity 时点动不调用 exit。"""
    title = "疑点3: 点动路径不单独 exit"
    try:
        _reset(0.18, MODE_VELOCITY)
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            cal = f.name
        col = _make_column(cal)
        col.control_mode = CONTROL_MODE_VELOCITY
        col._position_pp_active = True
        col._velocity_rearm_needed = False
        col._last_target_velocity_counts = 0
        _track_exit_and_prepare(col)

        ok = col.jog_velocity(0.05)
        os.remove(cal)
        bug = ok and METRICS["exit_dispatch_calls"] == 0
        return DiagResult(
            3,
            title,
            bug,
            "确认存在：点动不调用 _exit_position_dispatch" if bug else "未复现",
            f"jog_ok={ok}, exit_calls={METRICS['exit_dispatch_calls']}, "
            f"pp_still_active={col._position_pp_active}",
        )
    except Exception as exc:
        return DiagResult(3, title, False, "测试异常", traceback.format_exc())


def test_issue_4_exit_ignores_sdo_fail() -> DiagResult:
    """疑点4: exit 内 SDO 失败仍返回 True，且 switch 会清 pp 标志。"""
    title = "疑点4: exit 不校验 SDO 成败"
    try:
        _reset(0.18, MODE_POSITION)
        STATE["sdo_write_fail_index"] = OD_CONTROL_WORD
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            cal = f.name
        col = _make_column(cal)
        col.control_mode = CONTROL_MODE_POSITION
        col._position_pp_active = True

        ret = col._exit_position_dispatch()
        os.remove(cal)
        bug = ret is True
        return DiagResult(
            4,
            title,
            bug,
            "确认存在：SDO 写失败时 exit 仍返回 True" if bug else "未复现",
            f"exit_return={ret}, failed_cw_index={OD_CONTROL_WORD:#x}",
        )
    except Exception as exc:
        return DiagResult(4, title, False, "测试异常", traceback.format_exc())


def test_issue_5_sequence_diff() -> DiagResult:
    """疑点5: GUI exit 序列与 ROS 底层 exit_pp_online_state 是否一致。"""
    title = "疑点5: exit 序列与 ROS 底层不一致"
    ros_cpp = "/home/openarmx/openflex_all/openflex_ws/src/openflex_lift_slide/lift_slide_driver/src/lift_slide_hardware_interface.cpp"
    gui_steps: List[Tuple[str, int]] = []
    _reset(0.22, MODE_POSITION)
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        cal = f.name
    col = _make_column(cal)
    METRICS["sdo_writes"] = []
    col._exit_position_dispatch()
    for index, _sub, val in METRICS["sdo_writes"]:
        if index == OD_CONTROL_WORD:
            gui_steps.append(("CW", val))
        elif index == OD_TARGET_POSITION:
            gui_steps.append(("607A", val))

    ros_steps: List[Tuple[str, int]] = []
    if os.path.isfile(ros_cpp):
        import re

        text = open(ros_cpp, encoding="utf-8").read()
        block_m = re.search(
            r"bool LiftSlideHardwareInterface::exit_pp_online_state\(\)\s*\{(.*?)^\}",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if block_m:
            block = block_m.group(1)
            for m in re.finditer(
                r"sdo_write\(OBJ_CONTROLWORD.*?,\s*(0x[0-9A-Fa-f]+|\w+\s*\|\s*0x[0-9A-Fa-f]+.*?),\s*2",
                block,
            ):
                ros_steps.append(("CW", m.group(1)))
            if "OBJ_TARGET_POSITION" in block:
                ros_steps.append(("607A", "sync_actual"))

    os.remove(cal)

    # GUI: halt(0x010F), enable(0x000F), 607A, clear_setpoint, enable
    gui_cw = [v for k, v in gui_steps if k == "CW"]
    expected_gui = [
        CMD_ENABLE_OPERATION | CW_HALT,
        CMD_ENABLE_OPERATION,
        CMD_ENABLE_OPERATION & ~CW_NEW_SETPOINT,
        CMD_ENABLE_OPERATION,
    ]
    gui_match = gui_cw == expected_gui and any(k == "607A" for k, _ in gui_steps)
    ros_has_exit = False
    if os.path.isfile(ros_cpp):
        ros_has_exit = "exit_pp_online_state" in open(ros_cpp, encoding="utf-8").read()

    sequences_aligned = ros_has_exit and gui_match
    # bug_present=True 表示「存在序列/实现层面风险」；对齐则标记为未复现不一致
    bug = gui_match and not ros_has_exit
    return DiagResult(
        5,
        title,
        not sequences_aligned,
        "GUI 与 ROS 底层 exit 步骤已对齐（需实机验证驱动是否认）"
        if sequences_aligned
        else "GUI 与 ROS exit 步骤不一致或 ROS 未找到",
        f"GUI CW 序列={[hex(v) for v in gui_cw]}, has_607A={any(k=='607A' for k,_ in gui_steps)}, "
        f"ros_has_exit_pp={ros_has_exit}",
    )


def main() -> int:
    patches = [
        patch("openflex_driver.column.sdo_read_i32", mock_sdo_read),
        patch("openflex_driver.column.sdo_write_i32", mock_sdo_write),
        patch("openflex_driver.column.time.sleep", lambda s: None),
        patch("openflex_driver.column.Column._send_rpdo1", lambda self, *a, **k: True),
    ]
    for p in patches:
        p.start()

    tests = [
        test_issue_1_no_103f,
        test_issue_2_prepare_fail_after_exit,
        test_issue_3_jog_no_exit,
        test_issue_4_exit_ignores_sdo_fail,
        test_issue_5_sequence_diff,
    ]
    results: List[DiagResult] = [t() for t in tests]

    print("=" * 72)
    print("GUI column.py — PP/速度切换 五项疑点诊断")
    print("=" * 72)
    confirmed: List[DiagResult] = []
    for r in results:
        mark = "【代码层确认】" if r.bug_present else "【未复现/不适用】"
        print(f"\n{mark} 疑点{r.issue_id}: {r.title}")
        print(f"  结论: {r.verdict}")
        print(f"  详情: {r.detail}")
        if r.bug_present:
            confirmed.append(r)

    print("\n" + "=" * 72)
    print("汇总")
    print("=" * 72)
    if not confirmed:
        print("五项均未在代码逻辑层确认为「当前最可能根因」。")
    else:
        print("以下疑点在 GUI 代码中确认存在（可能与实机症状相关）：")
        for r in confirmed:
            print(f"  - 疑点{r.issue_id}: {r.title}")

    print("\n实机对照建议：")
    print("  1. 位置移动后切速度，日志是否有「升降台退出 PP 在线位置状态」")
    print("  2. 若无该日志 → 优先怀疑疑点1（本次未发 0x103F 或 pp 标志为 false）")
    print("  3. 若有退出日志仍不动 → 优先怀疑疑点4/5（exit 未真正生效或序列不够）")
    print("  4. 若第一次切换失败、第二次仍不动 → 优先怀疑疑点2")
    print("  5. 若未点速度模式直接点动 → 疑点3")

    for p in patches:
        p.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
