import sys

from PySide6.QtWidgets import QApplication
from controllers import MainController
from ui import OpenFlexMainWindow


def main():
    app = QApplication(sys.argv)
    window = OpenFlexMainWindow()
    controller = MainController(window)
    window.controller = controller  # 让 window 持有 controller 引用，用于关闭时清理
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
