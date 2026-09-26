import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from controllers.column_controller import ColumnController
from controllers.head_controller import HeadController


def test_head_check_connects_before_reading_status():
    controller = object.__new__(HeadController)
    calls = []
    controller._sync_joint_position_from_motor = lambda motor_id: calls.append(
        ("sync_position", motor_id)
    )
    controller._ensure_head_connected = lambda: calls.append("connect") or True
    controller.sync_status = lambda: calls.append("read_status")
    controller._current_head_motor_ids = lambda: [1, 2]
    controller.log = lambda *args: None

    controller.check_motors()

    assert calls == ["connect", ("sync_position", 1), ("sync_position", 2), "read_status"]


def test_column_check_connects_before_reading_status():
    controller = object.__new__(ColumnController)
    calls = []
    controller._ensure_column_connected = lambda: calls.append("connect") or True
    controller._poll_status_once = lambda: calls.append("read_status")

    controller.check_motors()

    assert calls == ["connect", "read_status"]
