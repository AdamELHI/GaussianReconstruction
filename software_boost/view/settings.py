import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)



class Settings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Parametres ")
        self.resize(650, 600)
        self.setMinimumSize(520, 400)

        self.file_path = None
        self.dataset_info = None

        self.main_layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_content = QWidget()
        self.content_layout = QVBoxLayout(self.scroll_content)
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area, 1)

        self.form_layout = QFormLayout()

        self.data_source_widget = QWidget()
        data_source_layout = QHBoxLayout(self.data_source_widget)
        data_source_layout.setContentsMargins(0, 0, 0, 0)
        self.csv_source_button = QRadioButton("Fichier CSV")
        self.generator_source_button = QRadioButton("Générateur interne")
        self.csv_source_button.setChecked(True)
        self.data_source_group = QButtonGroup(self)
        self.data_source_group.addButton(self.csv_source_button)
        self.data_source_group.addButton(self.generator_source_button)
        data_source_layout.addWidget(self.csv_source_button)
        data_source_layout.addWidget(self.generator_source_button)
        data_source_layout.addStretch()

        self.k_input = QSpinBox()
        self.k_input.setRange(1, 100000)
        self.k_input.setValue(100)

        self.n_iter_input = QSpinBox()
        self.n_iter_input.setRange(1, 100000000)
        self.n_iter_input.setValue(5000)

        self.snapshot_every_input = QSpinBox()
        self.snapshot_every_input.setRange(1, 1000000)
        self.snapshot_every_input.setValue(100)

        self.eta0_input = QDoubleSpinBox()
        self.eta0_input.setDecimals(6)
        self.eta0_input.setRange(0.000001, 10.0)
        self.eta0_input.setValue(0.2)

        self.eta_fin_input = QDoubleSpinBox()
        self.eta_fin_input.setDecimals(6)
        self.eta_fin_input.setRange(0.000001, 10.0)
        self.eta_fin_input.setValue(0.01)

        self.sigma0_input = QDoubleSpinBox()
        self.sigma0_input.setDecimals(6)
        self.sigma0_input.setRange(1.0, 1000.0)
        self.sigma0_input.setValue(101.3)

        self.sigma_fin_input = QDoubleSpinBox()
        self.sigma_fin_input.setDecimals(4)
        self.sigma_fin_input.setRange(0.0001, 100.0)
        self.sigma_fin_input.setValue(1.0)

        self.sigma_input = QDoubleSpinBox()
        self.sigma_input.setDecimals(6)
        self.sigma_input.setRange(0.0001, 10.0)
        self.sigma_input.setValue(0.09)

        self.form_layout.addRow("Source des données :", self.data_source_widget)
        self.form_layout.addRow("K :", self.k_input)
        self.form_layout.addRow("n_iter :", self.n_iter_input)
        self.form_layout.addRow("snapshot_every :", self.snapshot_every_input)
        self.form_layout.addRow("eta0 :", self.eta0_input)
        self.form_layout.addRow("eta_fin :", self.eta_fin_input)
        self.form_layout.addRow("sigma0 :", self.sigma0_input)
        self.form_layout.addRow("sigma_fin :", self.sigma_fin_input)
        self.form_layout.addRow("sigma labels :", self.sigma_input)
        self.content_layout.addLayout(self.form_layout)

        self.data_stack = QStackedWidget()
        self.build_csv_page()
        self.build_generator_page()
        self.content_layout.addWidget(self.data_stack)

        self.component_combo = QComboBox()
        self.component_combo.setEnabled(False)
        self.component_combo.addItem("Choisir un CSV")
        self.component_layout = QFormLayout()
        self.component_layout.addRow(
            "Composante affichee :",
            self.component_combo,
        )
        self.content_layout.addLayout(self.component_layout)

        self.dataset_label = QLabel("")
        self.dataset_label.setWordWrap(True)
        self.content_layout.addWidget(self.dataset_label)
        self.content_layout.addStretch()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Lancer")
        self.button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        ).setText("Annuler")
        self.main_layout.addWidget(self.button_box)

        self.generator_source_button.toggled.connect(self.update_data_source)
        self.csv_button.clicked.connect(self.choose_csv_file)
        self.header_checkbox.stateChanged.connect(self.update_csv_if_active)
        self.distribution_combo.currentIndexChanged.connect(
            self.update_distribution
        )
        self.generator_dimension_input.valueChanged.connect(
            self.update_generated_components
        )
        self.generator_dimension_input.valueChanged.connect(
            self.update_generated_info
        )
        self.generator_center_min_input.valueChanged.connect(
            self.update_generated_info
        )
        self.generator_center_max_input.valueChanged.connect(
            self.update_generated_info
        )
        self.gaussian_clusters_input.valueChanged.connect(
            self.update_generated_info
        )
        self.gaussian_points_input.valueChanged.connect(
            self.update_generated_info
        )
        self.uniform_step_input.valueChanged.connect(
            self.update_generated_info
        )
        self.clip_checkbox.toggled.connect(self.update_clip_controls)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.update_distribution()
        self.update_clip_controls(False)
        self.update_data_source(0)

    def build_csv_page(self):
        self.csv_page = QWidget()
        csv_page_layout = QVBoxLayout(self.csv_page)

        self.header_checkbox = QCheckBox("Le CSV contient un header")
        self.header_checkbox.setChecked(True)
        csv_page_layout.addWidget(self.header_checkbox)

        csv_layout = QHBoxLayout()
        self.file_label = QLabel("Aucun fichier selectionne")
        self.file_label.setWordWrap(True)
        self.csv_button = QPushButton("Charger un CSV")
        csv_layout.addWidget(self.file_label, 1)
        csv_layout.addWidget(self.csv_button)
        csv_page_layout.addLayout(csv_layout)

        self.data_stack.addWidget(self.csv_page)

    def build_generator_page(self):
        self.generator_page = QWidget()
        generator_layout = QVBoxLayout(self.generator_page)

        common_group = QGroupBox("Parametres communs du generateur")
        common_form = QFormLayout(common_group)

        self.distribution_combo = QComboBox()
        self.distribution_combo.addItem("Clusters gaussiens", "gaussian")
        self.distribution_combo.addItem("Grille uniforme", "uniform")

        self.generator_dimension_input = QSpinBox()
        self.generator_dimension_input.setRange(1, 50)
        self.generator_dimension_input.setValue(3)

        self.generator_center_min_input = QDoubleSpinBox()
        self.generator_center_min_input.setDecimals(4)
        self.generator_center_min_input.setRange(-1000000000.0, 1000000000.0)
        self.generator_center_min_input.setValue(0.0)

        self.generator_center_max_input = QDoubleSpinBox()
        self.generator_center_max_input.setDecimals(4)
        self.generator_center_max_input.setRange(-1000000000.0, 1000000000.0)
        self.generator_center_max_input.setValue(255.0)

        self.clip_checkbox = QCheckBox("Limiter les valeurs generees")
        self.clip_min_input = QDoubleSpinBox()
        self.clip_min_input.setDecimals(4)
        self.clip_min_input.setRange(-1000000000.0, 1000000000.0)
        self.clip_min_input.setValue(0.0)
        self.clip_max_input = QDoubleSpinBox()
        self.clip_max_input.setDecimals(4)
        self.clip_max_input.setRange(-1000000000.0, 1000000000.0)
        self.clip_max_input.setValue(255.0)

        common_form.addRow("Distribution :", self.distribution_combo)
        common_form.addRow("Dimension :", self.generator_dimension_input)
        common_form.addRow("Centre minimum :", self.generator_center_min_input)
        common_form.addRow("Centre maximum :", self.generator_center_max_input)
        common_form.addRow("", self.clip_checkbox)
        common_form.addRow("Limite minimum :", self.clip_min_input)
        common_form.addRow("Limite maximum :", self.clip_max_input)
        generator_layout.addWidget(common_group)

        self.distribution_stack = QStackedWidget()

        gaussian_page = QWidget()
        gaussian_form = QFormLayout(gaussian_page)
        self.gaussian_clusters_input = QSpinBox()
        self.gaussian_clusters_input.setRange(1, 10000)
        self.gaussian_clusters_input.setValue(4)
        self.gaussian_points_input = QSpinBox()
        self.gaussian_points_input.setRange(1, 1000000)
        self.gaussian_points_input.setValue(250)
        self.gaussian_sigma_input = QDoubleSpinBox()
        self.gaussian_sigma_input.setDecimals(4)
        self.gaussian_sigma_input.setRange(0.0001, 1000000000.0)
        self.gaussian_sigma_input.setValue(20.0)
        self.gaussian_seed_input = QSpinBox()
        self.gaussian_seed_input.setRange(-1, 2147483647)
        self.gaussian_seed_input.setSpecialValueText("Aleatoire")
        self.gaussian_seed_input.setValue(-1)
        gaussian_form.addRow("Nombre de clusters :", self.gaussian_clusters_input)
        gaussian_form.addRow("Points par cluster :", self.gaussian_points_input)
        gaussian_form.addRow("Ecart-type :", self.gaussian_sigma_input)
        gaussian_form.addRow("Graine aleatoire :", self.gaussian_seed_input)
        self.distribution_stack.addWidget(gaussian_page)

        uniform_page = QWidget()
        uniform_form = QFormLayout(uniform_page)
        self.uniform_step_input = QDoubleSpinBox()
        self.uniform_step_input.setDecimals(4)
        self.uniform_step_input.setRange(0.0001, 1000000000.0)
        self.uniform_step_input.setValue(10.0)
        uniform_form.addRow("Pas de la grille :", self.uniform_step_input)
        self.distribution_stack.addWidget(uniform_page)

        generator_layout.addWidget(self.distribution_stack)

        self.generator_info_label = QLabel("")
        self.generator_info_label.setWordWrap(True)
        generator_layout.addWidget(self.generator_info_label)

        self.data_stack.addWidget(self.generator_page)

    def get_data_source(self):
        if self.generator_source_button.isChecked():
            return "generator"
        return "csv"

    def update_data_source(self, index=None):
        generator_selected = self.get_data_source() == "generator"
        self.data_stack.setCurrentIndex(1 if generator_selected else 0)

        if generator_selected:
            self.update_generated_components()
            self.update_generated_info()
        else:
            self.update_dataset_info()

    def update_distribution(self, index=None):
        uniform_selected = self.distribution_combo.currentData() == "uniform"
        self.distribution_stack.setCurrentIndex(1 if uniform_selected else 0)
        self.update_generated_info()

    def update_clip_controls(self, checked):
        self.clip_min_input.setEnabled(bool(checked))
        self.clip_max_input.setEnabled(bool(checked))

    def update_csv_if_active(self, state=None):
        if self.get_data_source() == "csv":
            self.update_dataset_info()

    def choose_csv_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir un fichier CSV",
            "",
            "CSV Files (*.csv)",
        )

        if file_path:
            self.file_path = file_path
            self.file_label.setText(file_path)
            self.update_dataset_info()

    def update_dataset_info(self):
        self.component_combo.clear()
        self.component_combo.setEnabled(False)
        self.dataset_info = None

        if not self.file_path:
            self.component_combo.addItem("Choisir un CSV")
            self.dataset_label.setText("")
            return

        try:
            self.dataset_info = inspect_csv_dataset(
                self.file_path,
                skip_header=self.header_checkbox.isChecked(),
            )
        except Exception as e:
            self.component_combo.addItem("CSV invalide")
            self.dataset_label.setText(f"Erreur CSV : {e}")
            return

        for feature_position, feature_name in enumerate(
            self.dataset_info.feature_names
        ):
            if self.dataset_info.has_header:
                label = feature_name
            else:
                label = f"Composante {feature_name}"
            self.component_combo.addItem(label, feature_position)

        self.component_combo.setEnabled(self.component_combo.count() > 0)

        if self.dataset_info.label_index is None:
            label_text = "Aucune colonne label detectee"
        else:
            label_text = (
                f"Colonne label detectee : {self.dataset_info.label_name}"
            )

        self.dataset_label.setText(
            f"{len(self.dataset_info.feature_names)} composantes disponibles. "
            f"{label_text}."
        )

    def update_generated_components(self, value=None):
        if self.get_data_source() != "generator":
            return

        previous_index = max(self.component_combo.currentIndex(), 0)
        dimension = self.generator_dimension_input.value()
        self.component_combo.clear()
        for index in range(dimension):
            self.component_combo.addItem(f"x{index}", index)
        self.component_combo.setCurrentIndex(min(previous_index, dimension - 1))
        self.component_combo.setEnabled(True)

    def estimate_generated_points(self):
        if self.distribution_combo.currentData() == "gaussian":
            return (
                self.gaussian_clusters_input.value()
                * self.gaussian_points_input.value()
            )

        minimum = self.generator_center_min_input.value()
        maximum = self.generator_center_max_input.value()
        step = self.uniform_step_input.value()
        if maximum <= minimum:
            return 0

        value_count = math.floor((maximum - minimum) / step) + 1
        last_value = minimum + (value_count - 1) * step
        if not math.isclose(last_value, maximum, rel_tol=1e-9, abs_tol=1e-9):
            value_count += 1
        return value_count ** self.generator_dimension_input.value()

    def update_generated_info(self, value=None):
        if not hasattr(self, "generator_info_label"):
            return

        point_count = self.estimate_generated_points()
        dimension = self.generator_dimension_input.value()
        if self.distribution_combo.currentData() == "gaussian":
            class_count = self.gaussian_clusters_input.value()
            detail = f"{class_count} labels"
        else:
            detail = "1 label uniforme"

        self.generator_info_label.setText(
            f"Dataset en memoire : {point_count:,} points, "
            f"{dimension} composantes, {detail}. Aucun CSV ne sera cree."
        )
        if self.get_data_source() == "generator":
            self.dataset_label.setText(self.generator_info_label.text())

    def get_generator_parameters(self):
        clipping_enabled = self.clip_checkbox.isChecked()
        seed = self.gaussian_seed_input.value()
        return {
            "distribution": self.distribution_combo.currentData(),
            "dim": self.generator_dimension_input.value(),
            "center_min": self.generator_center_min_input.value(),
            "center_max": self.generator_center_max_input.value(),
            "n_clusters": self.gaussian_clusters_input.value(),
            "points_per_cluster": self.gaussian_points_input.value(),
            "sigma": self.gaussian_sigma_input.value(),
            "seed": None if seed == -1 else seed,
            "uniform_step": self.uniform_step_input.value(),
            "clip_min": (
                self.clip_min_input.value() if clipping_enabled else None
            ),
            "clip_max": (
                self.clip_max_input.value() if clipping_enabled else None
            ),
        }

    def accept(self):
        if self.get_data_source() == "csv":
            if not self.file_path:
                QMessageBox.warning(
                    self,
                    "CSV manquant",
                    "Choisis un fichier CSV avant de lancer la reconstruction.",
                )
                return
        else:
            if (
                self.generator_center_max_input.value()
                <= self.generator_center_min_input.value()
            ):
                QMessageBox.warning(
                    self,
                    "Bornes invalides",
                    "Le centre maximum doit etre superieur au centre minimum.",
                )
                return

            if (
                self.clip_checkbox.isChecked()
                and self.clip_max_input.value() <= self.clip_min_input.value()
            ):
                QMessageBox.warning(
                    self,
                    "Limites invalides",
                    "La limite maximum doit etre superieure a la limite minimum.",
                )
                return

            point_count = self.estimate_generated_points()
            if point_count > 1000000:
                QMessageBox.warning(
                    self,
                    "Dataset trop grand",
                    (
                        f"Cette configuration creerait {point_count:,} points. "
                        "Reduis la dimension, l'intervalle ou le nombre de points."
                    ),
                )
                return

        super().accept()

    def get_parameters(self):
        parameters = {
            "K": self.k_input.value(),
            "n_iter": self.n_iter_input.value(),
            "snapshot_every": self.snapshot_every_input.value(),
            "eta0": self.eta0_input.value(),
            "eta_fin": self.eta_fin_input.value(),
            "sigma0": self.sigma0_input.value(),
            "sigma_fin": self.sigma_fin_input.value(),
            "sigma": self.sigma_input.value(),
            "data_source": self.get_data_source(),
            "component_index": int(self.component_combo.currentData()),
            "component_name": self.component_combo.currentText(),
        }

        if self.get_data_source() == "generator":
            parameters["generator"] = self.get_generator_parameters()
        else:
            parameters["file_path"] = self.file_path
            parameters["has_header"] = self.header_checkbox.isChecked()

        return parameters
