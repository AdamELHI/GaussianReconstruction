from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
)


class Settings(QDialog):
    DEFAULT_PARAMETERS = {
        "fps": None,
        "start_time": None,
        "end_time": None,
        "total_train_iters": 7000,
        "use_gpu": True,
        "keep_temp": False,
        "colmap_track": False,
        "force_exhaustive_matcher": False,
        "video_ranges": {},
    }

    def __init__(self, parameters=None, input_paths=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Settings of the reconstruction")
        self.resize(420, 260)

        self.parameters = self.DEFAULT_PARAMETERS.copy()
        if parameters:
            self.parameters.update(parameters)
        self.input_paths = list(input_paths or [])
        self.video_range_inputs = {}
        if self.input_paths:
            self.resize(850, min(700, 360 + 36 * len(self.input_paths)))

        self.main_layout = QVBoxLayout(self)

        run_group = QGroupBox("Pipeline")
        run_form = QFormLayout(run_group)

        self.fps_input = QDoubleSpinBox()
        self.fps_input.setDecimals(2)
        self.fps_input.setRange(0.0, 120.0)
        self.fps_input.setSingleStep(0.5)
        self.fps_input.setSpecialValueText("Automatic")
        self.fps_input.setValue(float(self.parameters["fps"] or 0.0))
        self.fps_input.setToolTip(
            "Leave Automatic to select frames from camera motion, or enter "
            "a frame rate to control the temporal sampling density."
        )

        self.total_train_iters_input = QSpinBox()
        self.total_train_iters_input.setRange(1, 100000000)
        self.total_train_iters_input.setSingleStep(500)
        self.total_train_iters_input.setValue(
            int(self.parameters["total_train_iters"])
        )

        if not self.input_paths:
            run_form.addRow("Frames per second :", self.fps_input)
        run_form.addRow("Brush Iterations :", self.total_train_iters_input)

        self.start_time_input = None
        self.end_time_input = None
        video_ranges_group = None
        if self.input_paths:
            video_ranges_group = QGroupBox("Extraction settings for each video")
            video_ranges_layout = QVBoxLayout(video_ranges_group)
            video_ranges_table = QTableWidget(len(self.input_paths), 4)
            video_ranges_table.setHorizontalHeaderLabels(
                ["Video", "FPS", "Start (HH:MM:SS)", "End (HH:MM:SS)"]
            )
            video_ranges_table.horizontalHeader().setSectionResizeMode(
                0,
                QHeaderView.ResizeMode.Stretch,
            )
            saved_ranges = self.parameters.get("video_ranges") or {}
            for row, path in enumerate(self.input_paths):
                path_label = QLabel(path)
                path_label.setToolTip(path)
                video_ranges_table.setCellWidget(row, 0, path_label)

                saved_range = saved_ranges.get(path, {})
                video_fps_input = QDoubleSpinBox()
                video_fps_input.setDecimals(2)
                video_fps_input.setRange(0.0, 120.0)
                video_fps_input.setSingleStep(0.5)
                video_fps_input.setSpecialValueText("Automatic")
                saved_fps = saved_range.get(
                    "fps",
                    self.parameters.get("fps"),
                )
                video_fps_input.setValue(float(saved_fps or 0.0))
                video_fps_input.setToolTip(
                    "Leave Automatic to use motion-based frame selection for "
                    "this video, or enter a manual frame rate."
                )
                start_input = QLineEdit()
                start_input.setPlaceholderText("00:00:00")
                start_input.setText(
                    saved_range.get("start_time")
                    or self.parameters.get("start_time")
                    or ""
                )
                end_input = QLineEdit()
                end_input.setPlaceholderText("Until the end")
                end_input.setText(
                    saved_range.get("end_time")
                    or self.parameters.get("end_time")
                    or ""
                )
                video_ranges_table.setCellWidget(row, 1, video_fps_input)
                video_ranges_table.setCellWidget(row, 2, start_input)
                video_ranges_table.setCellWidget(row, 3, end_input)
                self.video_range_inputs[path] = (
                    video_fps_input,
                    start_input,
                    end_input,
                )
            video_ranges_layout.addWidget(video_ranges_table)
        else:
            self.start_time_input = QLineEdit()
            self.start_time_input.setPlaceholderText(
                "Optional, format : 00:00:10"
            )
            self.start_time_input.setText(self.parameters["start_time"] or "")
            self.end_time_input = QLineEdit()
            self.end_time_input.setPlaceholderText(
                "Optional, format : 00:01:30"
            )
            self.end_time_input.setText(self.parameters["end_time"] or "")
            run_form.addRow("Start of the video :", self.start_time_input)
            run_form.addRow("End of the video :", self.end_time_input)

        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        self.use_gpu_checkbox = QCheckBox(
            "Allow COLMAP to use the GPU when CUDA is available"
        )
        self.use_gpu_checkbox.setChecked(bool(self.parameters["use_gpu"]))

        self.keep_temp_checkbox = QCheckBox("Keep the temporary directory")
        self.keep_temp_checkbox.setChecked(bool(self.parameters["keep_temp"]))

        self.load_colmap_checkbox = QCheckBox("Open the COLMAP model in its GUI")
        self.load_colmap_checkbox.setChecked(bool(self.parameters["colmap_track"]))

        self.force_exhaustive_matcher_checkbox = QCheckBox(
            "Force exhaustive matching"
        )
        self.force_exhaustive_matcher_checkbox.setToolTip(
            "Compare every image pair, even when only one video is selected."
        )
        self.force_exhaustive_matcher_checkbox.setChecked(
            bool(self.parameters["force_exhaustive_matcher"])
        )

        options_layout.addWidget(self.use_gpu_checkbox)
        options_layout.addWidget(self.keep_temp_checkbox)
        options_layout.addWidget(self.load_colmap_checkbox)
        options_layout.addWidget(self.force_exhaustive_matcher_checkbox)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Apply"
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(
            "Cancel"
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.main_layout.addWidget(run_group)
        if video_ranges_group is not None:
            self.main_layout.addWidget(video_ranges_group)
        self.main_layout.addWidget(options_group)
        self.main_layout.addWidget(self.button_box)

    def get_parameters(self):
        if self.video_range_inputs:
            fps = None
            start_time = None
            end_time = None
            video_ranges = {}
            for path, inputs in self.video_range_inputs.items():
                video_fps_input, start_input, end_input = inputs
                video_start = start_input.text().strip()
                video_end = end_input.text().strip()
                video_ranges[path] = {
                    "fps": video_fps_input.value() or None,
                    "start_time": video_start or None,
                    "end_time": video_end or None,
                }
        else:
            fps = self.fps_input.value() or None
            start_time = self.start_time_input.text().strip() or None
            end_time = self.end_time_input.text().strip() or None
            video_ranges = {}

        return {
            "fps": fps,
            "start_time": start_time,
            "end_time": end_time,
            "video_ranges": video_ranges,
            "total_train_iters": self.total_train_iters_input.value(),
            "use_gpu": self.use_gpu_checkbox.isChecked(),
            "keep_temp": self.keep_temp_checkbox.isChecked(),
            "colmap_track": self.load_colmap_checkbox.isChecked(),
            "force_exhaustive_matcher": (
                self.force_exhaustive_matcher_checkbox.isChecked()
            ),
        }
