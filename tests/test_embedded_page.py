import os
import unittest

from PySide6.QtWidgets import QApplication, QGroupBox, QMainWindow, QScrollArea, QWidget


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


if __name__ == "__main__":
    unittest.main()
