from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox
from model.construction_model import ConstructionModel, DEFAULT_OUTPUT_DIR
import model.run_processing
from view.settings import Settings


class ReconstructionWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, model, input_path, output_path, parameters):
        super().__init__()
        self.model = model
        self.input_path = input_path
        self.output_path = output_path
        self.parameters = parameters

    @Slot()
    def run(self):
        try:
            result = self.model.run_reconstruction(
                self.input_path,
                self.output_path,
                progress_callback=self.progress.emit,
                **self.parameters,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.finished.emit(result)


class AppController:
    def __init__(self, view):
        self.view = view
        self.model = ConstructionModel()
        self.output_selected_manually = False
        self.reconstruction_parameters = Settings.DEFAULT_PARAMETERS.copy()
        self.reconstruction_thread = None
        self.reconstruction_worker = None
        self.connect_signals()

    def connect_signals(self):
        self.view.settings_button.clicked.connect(self.open_settings)
        self.view.load_reconstruct_button.clicked.connect(self.load_reconstruction)
        self.view.select_video_button.clicked.connect(self.select_input_file)
        self.view.select_output_button.clicked.connect(self.select_output_file)
        self.view.run_button.clicked.connect(self.run_reconstruction)
        self.view.load_button.clicked.connect(self.load_reconstruction)
        self.view.close_button.clicked.connect(self.view.close)

    def select_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Select a video",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.webm)",
        )
        if not file_path:
            return

        self.view.set_input_path(file_path)
        if not self.output_selected_manually:
            default_output = self.model.resolve_output_path(file_path, None)
            self.view.set_output_path(str(default_output))
        self.view.set_status(f"Video selected: {file_path}")

    def select_output_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self.view,
            "Select .ply file ",
            str(DEFAULT_OUTPUT_DIR),
            "PLY Files (*.ply)",
        )
        if not file_path:
            return

        self.view.set_output_path(file_path)
        self.output_selected_manually = True
        self.view.set_status(f"Ouput path : {file_path}")

    def run_reconstruction(self):
        if self.reconstruction_thread and self.reconstruction_thread.isRunning():
            QMessageBox.information(
                self.view,
                "Reconstruction in progress",
                "Reconstruction is already underway. Please wait for it to finish before starting a new one.",
            )
            return

        input_path = self.view.get_input_path()
        output_path = self.view.get_output_path()
        if not input_path:
            QMessageBox.warning(
                self.view,
                "Missing video",
                "Select a video before launching the reconstruction.",
            )
            return

        self.view.clear_progress()
        self.view.set_reconstruction_running(True)
        self.view.set_status("Reconstruction en cours...")
        self.view.add_progress_message(
            "Lauching the reconstruction from the selected video."
        )

        self.reconstruction_thread = QThread()
        self.reconstruction_worker = ReconstructionWorker(
            self.model,
            input_path,
            output_path,
            self.reconstruction_parameters.copy(),
        )
        self.reconstruction_worker.moveToThread(self.reconstruction_thread)

        self.reconstruction_thread.started.connect(self.reconstruction_worker.run)
        self.reconstruction_worker.progress.connect(self.view.add_progress_message)
        self.reconstruction_worker.finished.connect(
            self.handle_reconstruction_finished
        )
        self.reconstruction_worker.failed.connect(self.handle_reconstruction_failed)
        self.reconstruction_worker.finished.connect(self.reconstruction_thread.quit)
        self.reconstruction_worker.failed.connect(self.reconstruction_thread.quit)
        self.reconstruction_worker.finished.connect(
            self.reconstruction_worker.deleteLater
        )
        self.reconstruction_worker.failed.connect(
            self.reconstruction_worker.deleteLater
        )
        self.reconstruction_thread.finished.connect(
            self.reconstruction_thread.deleteLater
        )
        self.reconstruction_thread.finished.connect(self.clear_reconstruction_worker)
        self.reconstruction_thread.start()

    def handle_reconstruction_finished(self, result):
        self.view.set_reconstruction_running(False)
        self.view.set_status(result["message"])

        if result["path"]:
            self.view.set_output_path(result["path"])

        if result.get("placeholder"):
            self.view.add_progress_message(
                "The reconstruction could not be completed. A backup file has been created"
            )
            QMessageBox.information(
                self.view,
                "Partial reconstruction",
                result["message"],
            )
        else:
            self.view.add_progress_message(
                "Reconstruction completed. The 3D file is finished."
            )
            QMessageBox.information(
                self.view,
                "Reconstruction completed",
                result["message"],
            )

    def handle_reconstruction_failed(self, message):
        self.view.set_reconstruction_running(False)
        self.view.set_status("Error of reconstruction.")
        self.view.add_progress_message(
            "The reconstruction stopped before being able to create the 3D file."
        )
        QMessageBox.critical(self.view, "Error of reconstruction", message)

    def clear_reconstruction_worker(self):
        self.reconstruction_thread = None
        self.reconstruction_worker = None

    def load_reconstruction(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Loading a reconstruction",
            "",
            "PLY Files (*.ply)",
        )
        if not file_path:
            return

        try:
            result = self.model.load_reconstruction(file_path)
            model.run_processing.load(result["path"])
        except Exception as exc:
            QMessageBox.critical(self.view, "Error of loading", str(exc))
            return

        self.view.set_output_path(file_path)
        self.view.set_status(result["message"])
        QMessageBox.information(self.view, "Reconstruction loaded", result["message"])


    def open_settings(self):
        dialog = Settings(self.reconstruction_parameters, self.view)
        if not dialog.exec():
            return

        self.reconstruction_parameters = dialog.get_parameters()
        self.view.set_status(
            "Parameters applied  : "
            f"{self.reconstruction_parameters['fps']} fps, "
            f"{self.reconstruction_parameters['total_train_iters']} iterations."
        )
