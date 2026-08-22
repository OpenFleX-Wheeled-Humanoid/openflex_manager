import sys

from PySide6.QtWidgets import QApplication
from controllers import MainController
from ui import OpenFlexMainWindow


def main():
    app = QApplication(sys.argv)
    window = OpenFlexMainWindow()
    controller = MainController(window.motor_page)
    window.controller = controller
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
