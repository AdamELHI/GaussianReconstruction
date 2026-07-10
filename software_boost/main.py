from view.menu import Menu
from controller.app import AppController
from PySide6.QtWidgets import QApplication
import sys


def main():
    app = QApplication(sys.argv)

    view = Menu()
    controller = AppController(view)

    view.show()

    sys.exit(app.exec())

main()