from __future__ import annotations

import os
import sys
from pathlib import Path


SOFTWARE_DIR = Path(__file__).resolve().parents[1]
FROZEN = getattr(sys, "frozen", False)
PROJECT_ROOT = Path(
    os.environ.get("GAUSSIAN_RECONSTRUCTION_ROOT")
    or (Path(sys.executable).resolve().parent if FROZEN else SOFTWARE_DIR.parent)
).expanduser().resolve()
DATA_ROOT = Path(
    os.environ.get("GAUSSIAN_RECONSTRUCTION_DATA_ROOT", PROJECT_ROOT)
).expanduser().resolve()
BUNDLED_TOOLS_DIR = (
    Path(sys._MEIPASS) / "tools"
    if FROZEN and hasattr(sys, "_MEIPASS")
    else PROJECT_ROOT
)

DATASET_DIR = DATA_ROOT / "Dataset"
OUTPUT_DIR = DATA_ROOT / "Output"
LAST_RECONSTRUCTION_DIR = DATA_ROOT / "LastReconstruction"


def ensure_runtime_directories() -> None:
    for directory in (OUTPUT_DIR, LAST_RECONSTRUCTION_DIR):
        directory.mkdir(parents=True, exist_ok=True)
