from view.menu import Menu
from controller.app import AppController
from PySide6.QtWidgets import QApplication
from multiprocessing import freeze_support
from model.paths import ensure_runtime_directories
import sys


def main():
    ensure_runtime_directories()
    app = QApplication(sys.argv)

    view = Menu()
    controller = AppController(view)

    view.show()

    return app.exec()

if __name__ == "__main__":
    freeze_support()
    sys.exit(main())
