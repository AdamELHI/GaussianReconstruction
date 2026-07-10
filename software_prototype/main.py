
from PySide6.QtWidgets import QApplication
import sys

from PySide6.QtWidgets import ( 
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QSlider,
    QSizePolicy,
    QComboBox,
)
from PySide6.QtCore import Qt 
from PySide6.QtGui import QImage, QPixmap 
from PySide6.QtWidgets import QFileDialog, QMessageBox 
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parent.parent))

import run_processing





class MainMenu(QMainWindow):  # QMainWindow = Un prototype de menu deja fait par PyQT6 dont herite ma classe Menu pour gagner du temps
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Gaussian Reconstruction")
        self.resize(1000, 700)
        self.inputfile = ""
        self.outputfile = ""

        self.current_frame = None

        self.central_widget = QWidget()  # nom de l'element central dans QMainWindow
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)

        # =====================================================
        # Barre du haut
        # =====================================================
        self.top_bar_layout = QHBoxLayout()

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(50)

        self.load_construction_button = QPushButton("Load")

        self.load_construction_button.clicked.connect(self.load_construct_from_path)






        self.top_bar_layout.addWidget(self.settings_button)
        self.top_bar_layout.addWidget(self.load_construction_button)
        self.main_layout.addLayout(self.top_bar_layout)

        # =====================================================
        # Menu principal 
        # =====================================================
        self.main_button = QPushButton("Lancer la reconstruction")
        self.main_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_button.setStyleSheet("font-size: 24px;")
        self.main_button.clicked.connect(self.launch_reconstruction)
        self.select_file_button = QPushButton("Sélectionner un fichier")
        self.select_file_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.select_file_button.clicked.connect(self.select_file)
        self.main_layout.addWidget(self.select_file_button)
        self.main_layout.addWidget(self.main_button) 
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def launch_reconstruction(self):
        run_processing.run(self.inputfile, self.outputfile, fps=1.0, totaltrainiters=5000, usegpu=True, keeptemp=False, skipalign=False)

    def load_construct_from_path(self):
        file_name,_ = QFileDialog.getOpenFileName(self, "Select a file", ".ply", "Ply Files (*.ply)")
        run_processing.load(file_name)

    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select a file", ".mp4", "MP4 Files (*.mp4)")
        self.inputfile = file_name
        self.outputfile = file_name.replace(".mp4", ".ply")
def main():
    app = QApplication(sys.argv)
    
    menu = MainMenu()
    menu.show() 


    sys.exit(app.exec())

main()