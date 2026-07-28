from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox
from model.construction_model import ConstructionModel, DEFAULT_OUTPUT_DIR
from model.paths import DATASET_DIR
import model.run_processing
from view.settings import Settings


class ReconstructionWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        model,
        input_path,
        output_path,
        parameters,
        pause_controller,
    ):
        super().__init__()
        self.model = model
        self.input_path = input_path
        self.output_path = output_path
        self.parameters = parameters
        self.pause_controller = pause_controller

    @Slot()
    def run(self):
        try:
            result = self.model.run_reconstruction(
                self.input_path,
                self.output_path,
                progress_callback=self.progress.emit,
                pause_controller=self.pause_controller,
                **self.parameters,
            )
        except model.run_processing.ReconstructionCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.finished.emit(result)


class ReconstructionLoadWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, reconstruction_model, file_path):
        super().__init__()
        self.reconstruction_model = reconstruction_model
        self.file_path = file_path

    @Slot()
    def run(self):
        try:
            result = self.reconstruction_model.load_reconstruction(self.file_path)
            model.run_processing.load(
                result["path"],
                progress_callback=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        self.finished.emit(result)


class AppController(QObject):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.model = ConstructionModel()
        self.output_selected_manually = False
        self.reconstruction_parameters = Settings.DEFAULT_PARAMETERS.copy()
        self.reconstruction_thread = None
        self.reconstruction_worker = None
        self.load_thread = None
        self.load_worker = None
        self.pause_controller = None
        self.connect_signals()

    def connect_signals(self):
        self.view.settings_button.clicked.connect(self.open_settings)
        self.view.load_reconstruct_button.clicked.connect(self.load_reconstruction)
        self.view.select_video_button.clicked.connect(self.select_input_file)
        self.view.select_output_button.clicked.connect(self.select_output_file)
        self.view.run_button.clicked.connect(self.run_reconstruction)
        self.view.pause_button.clicked.connect(self.toggle_reconstruction_pause)
        self.view.cancel_button.clicked.connect(self.cancel_reconstruction)
        self.view.load_button.clicked.connect(self.load_reconstruction)
        self.view.close_button.clicked.connect(self.view.close)

    def select_input_file(self):
        videos_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.MoviesLocation
        )
        if videos_directory and Path(videos_directory).is_dir():
            initial_directory = videos_directory
        else:
            DATASET_DIR.mkdir(parents=True, exist_ok=True)
            initial_directory = str(DATASET_DIR)

        file_path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Select a video",
            initial_directory,
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
        suggested_output = self.view.get_output_path() or str(DEFAULT_OUTPUT_DIR)
        file_path, _ = QFileDialog.getSaveFileName(
            self.view,
            "Select .ply file ",
            suggested_output,
            "PLY Files (*.ply)",
        )
        if not file_path:
            return

        self.view.set_output_path(file_path)
        self.output_selected_manually = True
        self.view.set_status(f"Ouput path : {file_path}")

    def run_reconstruction(self):
        if self.load_thread and self.load_thread.isRunning():
            QMessageBox.information(
                self.view,
                "Loading in progress",
                "Wait for the 3D file to finish loading before starting a reconstruction.",
            )
            return
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

        try:
            self.model.validate_reconstruction_parameters(
                input_path,
                self.reconstruction_parameters,
            )
        except ValueError as exc:
            QMessageBox.warning(
                self.view,
                "Invalid reconstruction settings",
                str(exc),
            )
            return

        self.view.clear_progress()
        self.view.set_reconstruction_running(True)
        self.view.set_status("Reconstruction en cours...")
        self.view.add_progress_message(
            "Lauching the reconstruction from the selected video."
        )

        self.reconstruction_thread = QThread()
        self.pause_controller = model.run_processing.PauseManager()
        self.reconstruction_worker = ReconstructionWorker(
            self.model,
            input_path,
            output_path,
            self.reconstruction_parameters.copy(),
            self.pause_controller,
        )
        self.reconstruction_worker.moveToThread(self.reconstruction_thread)

        self.reconstruction_thread.started.connect(self.reconstruction_worker.run)
        queued_connection = Qt.ConnectionType.QueuedConnection
        self.reconstruction_worker.progress.connect(
            self.view.add_progress_message,
            queued_connection,
        )
        self.reconstruction_worker.finished.connect(
            self.handle_reconstruction_finished,
            queued_connection,
        )
        self.reconstruction_worker.failed.connect(
            self.handle_reconstruction_failed,
            queued_connection,
        )
        self.reconstruction_worker.cancelled.connect(
            self.handle_reconstruction_cancelled,
            queued_connection,
        )
        self.reconstruction_worker.finished.connect(self.reconstruction_thread.quit)
        self.reconstruction_worker.failed.connect(self.reconstruction_thread.quit)
        self.reconstruction_worker.cancelled.connect(self.reconstruction_thread.quit)
        self.reconstruction_worker.finished.connect(
            self.reconstruction_worker.deleteLater
        )
        self.reconstruction_worker.failed.connect(
            self.reconstruction_worker.deleteLater
        )
        self.reconstruction_worker.cancelled.connect(
            self.reconstruction_worker.deleteLater
        )
        self.reconstruction_thread.finished.connect(
            self.reconstruction_thread.deleteLater
        )
        self.reconstruction_thread.finished.connect(
            self.clear_reconstruction_worker,
            queued_connection,
        )
        self.reconstruction_thread.start()

    def cancel_reconstruction(self):
        if not self.reconstruction_thread or not self.reconstruction_thread.isRunning():
            return
        if self.pause_controller is None:
            return

        answer = QMessageBox.question(
            self.view,
            "Cancel reconstruction",
            "Do you really want to cancel the current reconstruction?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.view.set_reconstruction_cancelling()
        self.view.set_status("Cancelling the reconstruction...")
        self.view.add_progress_message("Cancellation requested.")
        self.pause_controller.cancel()

    def toggle_reconstruction_pause(self):
        if not self.reconstruction_thread or not self.reconstruction_thread.isRunning():
            return
        if self.pause_controller is None:
            return

        if self.pause_controller.is_paused:
            self.pause_controller.resume()
            self.view.set_reconstruction_paused(False)
            self.view.set_status("Reconstruction in progress...")
            self.view.add_progress_message("Reconstruction resumed.")
        else:
            self.pause_controller.pause()
            self.view.set_reconstruction_paused(True)
            self.view.set_status("Reconstruction paused.")
            self.view.add_progress_message("Reconstruction paused.")

    @Slot(dict)
    def handle_reconstruction_finished(self, result):
        if self.pause_controller:
            self.pause_controller.resume()
        self.view.set_reconstruction_running(False)
        self.view.set_status(result["message"])

        if result["path"]:
            self.view.set_output_path(result["path"])

        if result.get("placeholder"):
            self.view.set_status("Reconstruction failed.")
            self.view.add_progress_message(
                "The reconstruction could not be completed. A backup file has been created"
            )
            self.view.add_progress_message(result["message"])
            QMessageBox.critical(
                self.view,
                "Reconstruction failed",
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

    @Slot(str)
    def handle_reconstruction_failed(self, message):
        if self.pause_controller:
            self.pause_controller.resume()
        self.view.set_reconstruction_running(False)
        self.view.set_status("Error of reconstruction.")
        self.view.add_progress_message(
            "The reconstruction stopped before being able to create the 3D file."
        )
        self.view.add_progress_message(f"Error details: {message}")
        QMessageBox.critical(self.view, "Error of reconstruction", message)

    @Slot()
    def handle_reconstruction_cancelled(self):
        self.view.set_reconstruction_running(False)
        self.view.set_status("Reconstruction cancelled.")
        self.view.add_progress_message("The reconstruction was cancelled.")

    def clear_reconstruction_worker(self):
        self.reconstruction_thread = None
        self.reconstruction_worker = None
        self.pause_controller = None

    def load_reconstruction(self):
        if self.reconstruction_thread and self.reconstruction_thread.isRunning():
            QMessageBox.information(
                self.view,
                "Reconstruction in progress",
                "Wait for the reconstruction to finish before loading a file.",
            )
            return
        if self.load_thread and self.load_thread.isRunning():
            QMessageBox.information(
                self.view,
                "Loading in progress",
                "A reconstruction file is already being loaded.",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self.view,
            "Loading a reconstruction",
            "",
            "PLY Files (*.ply)",
        )
        if not file_path:
            return

        self.start_reconstruction_loading(file_path)

    def start_reconstruction_loading(self, file_path):
        self.view.clear_progress()
        self.view.set_reconstruction_loading(True)
        self.view.set_status("Loading the reconstruction...")
        self.view.add_progress_message(f"Opening the 3D file: {file_path}")

        self.load_thread = QThread()
        self.load_worker = ReconstructionLoadWorker(self.model, file_path)
        self.load_worker.moveToThread(self.load_thread)

        queued_connection = Qt.ConnectionType.QueuedConnection
        self.load_thread.started.connect(self.load_worker.run)
        self.load_worker.progress.connect(
            self.view.add_progress_message,
            queued_connection,
        )
        self.load_worker.finished.connect(
            self.handle_load_finished,
            queued_connection,
        )
        self.load_worker.failed.connect(
            self.handle_load_failed,
            queued_connection,
        )
        self.load_worker.finished.connect(self.load_thread.quit)
        self.load_worker.failed.connect(self.load_thread.quit)
        self.load_worker.finished.connect(self.load_worker.deleteLater)
        self.load_worker.failed.connect(self.load_worker.deleteLater)
        self.load_thread.finished.connect(self.load_thread.deleteLater)
        self.load_thread.finished.connect(
            self.clear_load_worker,
            queued_connection,
        )
        self.load_thread.start()

    @Slot(dict)
    def handle_load_finished(self, result):
        self.view.set_reconstruction_loading(False)
        self.view.set_output_path(result["path"])
        self.view.set_status(result["message"])
        self.view.add_progress_message("The reconstruction file has been loaded.")
        QMessageBox.information(
            self.view,
            "Reconstruction loaded",
            result["message"],
        )

    @Slot(str)
    def handle_load_failed(self, message):
        self.view.set_reconstruction_loading(False)
        self.view.set_status("The reconstruction file could not be loaded.")
        self.view.add_progress_message(f"Loading error: {message}")
        QMessageBox.critical(self.view, "Error of loading", message)

    @Slot()
    def clear_load_worker(self):
        self.load_thread = None
        self.load_worker = None


    def open_settings(self):
        dialog = Settings(self.reconstruction_parameters, self.view)
        while dialog.exec():
            parameters = dialog.get_parameters()
            try:
                self.model.validate_reconstruction_parameters(
                    self.view.get_input_path() or None,
                    parameters,
                )
            except ValueError as exc:
                QMessageBox.warning(
                    self.view,
                    "Invalid reconstruction settings",
                    str(exc),
                )
                continue

            self.reconstruction_parameters = parameters
            self.view.set_status(
                "Parameters applied  : "
                f"{self.reconstruction_parameters['fps']} fps, "
                f"{self.reconstruction_parameters['total_train_iters']} iterations."
            )
            return
