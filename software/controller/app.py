from PySide6.QtWidgets import QApplication, QWidget 

import sys 

app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("Test Window")
window.resize(1200, 800)
window.show()

app.exec()