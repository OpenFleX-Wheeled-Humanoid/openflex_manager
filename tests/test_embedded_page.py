import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QGroupBox,
    QMainWindow,
    QScrollArea,
    QSplitter,
    QStyle,
    QStyleOptionSpinBox,
    QWidget,
)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class EmbeddedMotorManagementPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_is_embeddable_and_keeps_all_subsystems(self):
        try:
            from ui import MotorManagementPage
        except ImportError:
            self.fail("ui.MotorManagementPage is missing")

        page = MotorManagementPage()
        self.assertIsInstance(page, QWidget)
        self.assertNotIsInstance(page, QMainWindow)
        self.assertEqual(page.left_tabs.count(), 4)
        self.assertEqual(
            [page.left_tabs.tabText(index) for index in range(4)],
            ["头部", "双臂", "升降台", "底盘"],
        )
        self.assertTrue(hasattr(page, "btn_start_can"))
        self.assertTrue(hasattr(page, "btn_chassis_estop"))
        self.assertEqual(page.current_theme, "light")
        page.close()

    def test_minimum_control_center_width_does_not_overlap_head_panels(self):
        from ui import MotorManagementPage

        page = MotorManagementPage()
        page.resize(806, 640)
        page.show()
        self.app.processEvents()

        controls = page.findChild(QScrollArea, "headScrollArea")
        status = page.findChild(QGroupBox, "headStatePanel")
        self.assertLess(controls.geometry().right(), status.geometry().left())
        page.close()

    def test_step_and_chassis_spinboxes_have_visible_up_down_button_regions(self):
        from ui import MotorManagementPage

        page = MotorManagementPage()
        page.resize(806, 640)
        page.show()
        self.app.processEvents()

        spinboxes = [page.spin_head_step]
        spinboxes.extend(
            control["spin_speed"] for control in page.chassis_um_controls.values()
        )
        spinboxes.extend(
            control["spin_angle"] for control in page.chassis_rs_controls.values()
        )

        for spinbox in spinboxes:
            self.assertEqual(
                spinbox.buttonSymbols(),
                QAbstractSpinBox.ButtonSymbols.UpDownArrows,
            )
            option = QStyleOptionSpinBox()
            spinbox.initStyleOption(option)
            style = spinbox.style()
            up = style.subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                option,
                QStyle.SubControl.SC_SpinBoxUp,
                spinbox,
            )
            down = style.subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                option,
                QStyle.SubControl.SC_SpinBoxDown,
                spinbox,
            )
            self.assertGreaterEqual(up.width(), 18)
            self.assertGreaterEqual(down.width(), 18)
            self.assertGreaterEqual(up.height(), 12)
            self.assertGreaterEqual(down.height(), 12)

        page.close()

    def test_device_tabs_use_draggable_horizontal_state_splitters(self):
        from ui import MotorManagementPage

        page = MotorManagementPage()
        page.resize(1200, 820)
        page.show()
        self.app.processEvents()

        names = (
            "headStateSplitter",
            "dualArmStateSplitter",
            "columnStateSplitter",
            "chassisStateSplitter",
        )
        page._suppress_chassis_tab_prompt = True
        for index, name in enumerate(names):
            page.left_tabs.setCurrentIndex(index)
            self.app.processEvents()
            splitter = page.findChild(QSplitter, name)
            self.assertIsNotNone(splitter, name)
            self.assertEqual(splitter.orientation(), Qt.Orientation.Horizontal)
            self.assertFalse(splitter.childrenCollapsible())
            self.assertEqual(splitter.count(), 2)
            before = splitter.sizes()
            splitter.setSizes([before[0] + 80, max(1, before[1] - 80)])
            self.app.processEvents()
            self.assertNotEqual(splitter.sizes(), before)
        page.close()


if __name__ == "__main__":
    unittest.main()
