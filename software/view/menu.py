from PySide6.QtWidgets import QMenu, QMenuBar, QMainWindow


class Menu(QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Menu Example")

        # Create a menu bar
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)

        # Create a file menu
        file_menu = QMenu("File", self)
        menu_bar.addMenu(file_menu)

        # Add actions to the file menu
        new_action = file_menu.addAction("New")
        open_action = file_menu.addAction("Open")
        save_action = file_menu.addAction("Save")
        exit_action = file_menu.addAction("Exit")

        # Connect actions to methods
        new_action.triggered.connect(self.new_file)
        open_action.triggered.connect(self.open_file)
        save_action.triggered.connect(self.save_file)
        exit_action.triggered.connect(self.close)