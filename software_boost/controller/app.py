from PySide6.QtWidgets import QApplication, QWidget, QComboBox, QMessageBox , QFileDialog
from model.storage import save_construction_file, load_construction_file 
from controller.play_controller import PlayController
from view.settings import Settings 
from model.construction_model import ConstructionModel
import sys 
from pathlib import Path


class AppController:
    def __init__(self, view):
        self.view = view

        # Model
        self.model = ConstructionModel()

        # Playback controller
        self.play_controller = PlayController(self.model, self.view)

        # Connect UI
        self.connect_signals()

    # =========================================================
    # UI CONNECTIONS
    # =========================================================

    def connect_signals(self):
        self.view.settings_button.clicked.connect(self.open_settings)
        self.view.load_reconstruct_button.clicked.connect(self.load_som)
        self.view.save_reconstruct_button.clicked.connect(self.save_som)
        self.view.close_button.clicked.connect(self.view.close)

        self.view.play_button.clicked.connect(self.play_controller.play)
        self.view.pause_button.clicked.connect(self.play_controller.pause)
        self.view.stop_button.clicked.connect(self.play_controller.stop)
        self.view.slider.valueChanged.connect(self.play_controller.go_to_frame)

    def change_topology(self, index=None):
        topology = self.view.get_selected_topology()
        self.model.set_topology(topology)

        # Changer 1D/2D change la forme de la carte, donc les anciens snapshots
        # ne correspondent plus forcement au mode selectionne.
        self.play_controller.pause()
        self.play_controller.set_frames(None)
        self.model.reset_snapshots()
        self.view.hide_legend()
        self.view.save_som_button.setEnabled(False)

        self.view.current_frame = None
        self.view.image_label.setText(
            f"Mode SOM {topology.upper()} sélectionné. Lance l'entraînement avec ⚙."
        )
        self.view.mode_logiciel.setCurrentIndex(-1)
        self.view.update_iteration_label(0)
        self.view.update_slider(0, 0)

    def load(self, index):
        try:
            self.load_mode(index)
        except Exception as e:
            print("Erreur:", e)
            QMessageBox.warning(self.view, "Mode indisponible", str(e))

    def load_mode(self, index):
        if index == 0:
            self.play_controller.load_neuron_frames()
        elif index == 1:
            self.play_controller.load_rgb_frames()
        elif index == 2:
            self.play_controller.load_component_frames()
        elif index == 3:
            self.play_controller.load_noir_blanc_frames()
        elif index == 4:
            self.play_controller.load_label_frames()
        elif index == 5:
            self.play_controller.load_proba_frames()
        else:
            raise ValueError("Le mode d'affichage est invalide")

    # =========================================================
    # SAVE / LOAD SOM
    # =========================================================

    def save_som(self):
        if not self.mode_has_frames(2):
            QMessageBox.warning(
                self.view,
                "Aucune SOM",
                "Entraine ou charge une SOM avant de l'enregistrer.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self.view,
            "Enregistrer la SOM",
            "som_session.som",
            "SOM PlayTest (*.som)",
        )
        if not file_path:
            return

        try:
            saved_path = self.save_som_to_path(file_path)
        except Exception as e:
            QMessageBox.critical(
                self.view,
                "Erreur d'enregistrement",
                str(e),
            )
            return

        QMessageBox.information(
            self.view,
            "SOM enregistree",
            f"La SOM a ete enregistree dans :\n{saved_path}",
        )

    def save_construction_to_path(self, file_path):
        path = Path(file_path)
        if path.suffix.lower() != ".som":
            path = Path(f"{path}.som")

        session_state = {
            "model": self.model.export_state(),
            "playback": {
                "snapshot_every": self.play_controller.snapshot_every,
                "selected_mode": self.view.mode_logiciel.currentIndex(),
                "current_frame": self.play_controller.get_current_index(),
                "fps": self.play_controller.fps,
                "loop": self.play_controller.loop,
            },
        }
        save_construction_file(path, session_state)
        return str(path)

    def load_som(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Charger un fichier de confiance",
            "",
            "Gaussian Reconstruction (*.ply)",
        )
        if not file_path:
            return

        answer = QMessageBox.warning(
            self.view,
            "Fichier pickle",
            (
                "Les fichiers pickle peuvent executer du code. "
                "Charge uniquement un fichier .som cree par cette application "
                "ou provenant d'une source de confiance.\n\nContinuer ?"
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.load_som_from_path(file_path)
        except Exception as e:
            QMessageBox.critical(
                self.view,
                "Erreur de chargement",
                str(e),
            )
            return

        QMessageBox.information(
            self.view,
            "Reconstruction chargée",
            "La reconstruction est prête.",
        )

    def load_construct_from_path(self, file_path):
        session_state = load_construction_file(file_path)
        model_state = session_state.get("model")
        playback_state = session_state.get("playback", {})

        loaded_model = ConstructionModel()
        loaded_model.import_state(model_state)

        self.play_controller.pause()
        self.model = loaded_model
        self.play_controller.model = loaded_model
        self.play_controller.snapshot_every = max(
            1, int(playback_state.get("snapshot_every", 1))
        )
        self.play_controller.set_fps(float(playback_state.get("fps", 20)))
        self.play_controller.set_loop(playback_state.get("loop", False))

        self.view.topology_combo.blockSignals(True)
        self.view.topology_combo.setCurrentIndex(
            0 if self.model.is_1d() else 1
        )
        self.view.topology_combo.blockSignals(False)

        preferred_mode = int(playback_state.get("selected_mode", 2))
        candidate_modes = [preferred_mode, 2, 3, 4, 5, 0, 1]
        selected_mode = next(
            (
                index
                for index in candidate_modes
                if self.mode_has_frames(index)
            ),
            None,
        )
        if selected_mode is None:
            raise ValueError("Le fichier SOM ne contient aucune video lisible")

        self.view.mode_logiciel.setCurrentIndex(selected_mode)
        self.load_mode(selected_mode)
        self.play_controller.go_to_frame(
            int(playback_state.get("current_frame", 0))
        )
        self.view.save_som_button.setEnabled(True)
        self.view.setWindowTitle(
            f"SOM Visualizer - {Path(file_path).name}"
        )

    # =========================================================
    # SETTINGS
    # =========================================================

    def open_settings(self):
        dialog = Settings(self.view)

        if dialog.exec():  # OK pressed
            params = dialog.get_parameters()

            try:
                self.run_som(params)
            except Exception as e:
                print("Erreur:", e)
                QMessageBox.critical(
                    self.view,
                    "Erreur d'entrainement",
                    str(e),
                )

    # =========================================================
    #
    # =========================================================

    def run(self, params):


        print(f"Training Gaussian {self.model.topology.upper()}...")
        self.model.train(params["snapshot_every"])
        print("Training finished")

        # Affiche par defaut la composante choisie, utilisable dans toutes les dimensions.
        self.view.save_som_button.setEnabled(True)
        self.view.setWindowTitle("SOM Visualizer")
