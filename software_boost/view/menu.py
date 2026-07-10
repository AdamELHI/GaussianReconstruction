from PySide6.QtWidgets import QMenu, QMenuBar, QMainWindow,QWidget, QLabel , QVBoxLayout, QPushButton, QHBoxLayout, QSlider, QSizePolicy, QComboBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPixmap #A voir pour Pixmap

class Menu(QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Menu Example")
        self.resize(1200,800)
        # Create a menu bar
        self.central_widget = QWidget()  # nom de l'element central dans QMainWindow
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout(self.central_widget)

        # =====================================================
        # Barre du haut
        # =====================================================
        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(50)
        self.load_reconstruct_button = QPushButton("Load Construction")
        self.save_reconstruct_button = QPushButton("Save Construction")
        self.save_reconstruct_button.setEnabled(False)
        
        self.iteration_label = QLabel("Itération : 0")
        self.iteration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.close_button = QPushButton("X")
        self.close_button.setFixedWidth(50)

        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.setValue(0)


        self.top_bar_layout.addWidget(self.settings_button)
        self.top_bar_layout.addWidget(self.load_reconstruct_button)
        self.top_bar_layout.addWidget(self.save_reconstruct_button)
        self.top_bar_layout.addStretch()
        self.top_bar_layout.addWidget(self.iteration_label)
        self.top_bar_layout.addStretch()
        self.top_bar_layout.addWidget(self.close_button)



        self.main_layout.addLayout(self.top_bar_layout)

