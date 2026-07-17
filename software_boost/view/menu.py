from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class Menu(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gaussian Reconstruction")
        self.resize(1000, 700)

        self.input_path = ""
        self.output_path = ""

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

#Construction de la barre du haut

        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(50)
        self.load_reconstruct_button = QPushButton("Charger un .ply")
        self.save_reconstruct_button = QPushButton("Enregistrer")
        self.save_reconstruct_button.setEnabled(False)
        self.close_button = QPushButton("X")
        self.close_button.setFixedWidth(50)
        self.top_bar_layout.addWidget(self.settings_button)
        self.top_bar_layout.addWidget(self.load_reconstruct_button)
        self.top_bar_layout.addWidget(self.save_reconstruct_button)
        self.top_bar_layout.addStretch()
        self.top_bar_layout.addWidget(self.close_button)
        self.main_layout.addLayout(self.top_bar_layout)

        self.content_layout = QVBoxLayout()
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

#Labels et boutons pour selectionner les fichiers d'entrée et de sortie, lancer la reconstruction, charger une reconstruction, afficher le status et la barre de progression (progression + log à faire)

        self.input_label = QLabel("Vidéo : Aucune vidéo sélectionnée")
        self.input_label.setWordWrap(True)
        self.output_label = QLabel("Sortie : Aucun chemin sélectionné")
        self.output_label.setWordWrap(True)

        self.select_video_button = QPushButton("Sélectionner une vidéo")
        self.select_video_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.select_output_button = QPushButton("Choisir le chemin d'exportation de la reconstruction")
        self.select_output_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.run_button = QPushButton("Lancer la reconstruction")
        self.run_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.load_button = QPushButton("Charger une reconstruction")
        self.load_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )


        self.status_label = QLabel("Aucune reconstruction lancée.")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self.progress_log = QPlainTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_log.setPlaceholderText(
            "Les étapes de reconstruction apparaitront ici."
        )
        self.progress_log.setMinimumHeight(180)
        self.progress_log.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.content_layout.addWidget(self.input_label)
        self.content_layout.addWidget(self.output_label)
        self.content_layout.addWidget(self.select_video_button)
        self.content_layout.addWidget(self.select_output_button)
        self.content_layout.addWidget(self.run_button)
        self.content_layout.addWidget(self.load_button)
        self.content_layout.addWidget(self.status_label)
        self.content_layout.addWidget(self.progress_bar)
        self.content_layout.addWidget(self.progress_log)

        self.main_layout.addLayout(self.content_layout)

    def set_input_path(self, path: str) -> None:
        self.input_path = path
        if path:
            self.input_label.setText(f"Vidéo : {path}")
        else:
            self.input_label.setText("Vidéo : Aucune vidéo sélectionnée")

    def set_output_path(self, path: str) -> None:
        self.output_path = path
        if path:
            self.output_label.setText(f"Sortie : {path}")
        else:
            self.output_label.setText("Sortie : Aucun fichier de sortie")

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def clear_progress(self) -> None:
        self.progress_log.clear()

    def add_progress_message(self, message: str) -> None:
        if not message:
            return

        self.progress_log.appendPlainText(f"- {message}")
        scroll_bar = self.progress_log.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def set_reconstruction_running(self, is_running: bool) -> None:
        self.run_button.setEnabled(not is_running)
        self.select_video_button.setEnabled(not is_running)
        self.select_output_button.setEnabled(not is_running)
        self.settings_button.setEnabled(not is_running)
        self.load_button.setEnabled(not is_running)
        self.load_reconstruct_button.setEnabled(not is_running)
        self.close_button.setEnabled(not is_running)

        if is_running:
            self.run_button.setText("Reconstruction en cours...")
            self.progress_bar.setRange(0, 0)
        else:
            self.run_button.setText("Lancer la reconstruction")
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)

    def get_input_path(self) -> str:
        return self.input_path

    def get_output_path(self) -> str:
        return self.output_path
