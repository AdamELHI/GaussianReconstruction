from __future__ import annotations

import os
import sys
from pathlib import Path


SOFTWARE_DIR = Path(__file__).resolve().parents[1]


def project_root() -> Path:
    """Return the root of the GaussianReconstruction installation."""
    override = os.environ.get("GAUSSIAN_RECONSTRUCTION_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        if executable_dir.name.casefold() == "software":
            return executable_dir.parent
        if (
            executable_dir.name.casefold() == "dist"
            and executable_dir.parent.name.casefold() == "software"
        ):
            return executable_dir.parent.parent
        if (
            executable_dir.parent.name.casefold() == "dist"
            and executable_dir.parent.parent.name.casefold() == "software"
        ):
            return executable_dir.parent.parent.parent
        return executable_dir

    return SOFTWARE_DIR.parent


def bundled_tools_dir() -> Path:
    """Return the directory containing tools embedded by PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "tools"
    return project_root()


PROJECT_ROOT = project_root()


def data_root() -> Path:
    """Return the runtime data directory, optionally overridden by the user."""
    override = os.environ.get("GAUSSIAN_RECONSTRUCTION_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT


DATA_ROOT = data_root()
BRUSH_DIR = PROJECT_ROOT / "Brush"
COLMAP_DIR = PROJECT_ROOT / "Colmap"
DATASET_DIR = DATA_ROOT / "Dataset"
OUTPUT_DIR = DATA_ROOT / "Output"
LAST_RECONSTRUCTION_DIR = DATA_ROOT / "LastReconstruction"

BUNDLED_TOOLS_DIR = bundled_tools_dir()
BUNDLED_BRUSH_DIR = BUNDLED_TOOLS_DIR / "brush"
BUNDLED_COLMAP_DIR = BUNDLED_TOOLS_DIR / "colmap"


def ensure_runtime_directories() -> None:
    for directory in (OUTPUT_DIR, LAST_RECONSTRUCTION_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def first_existing_file(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def find_executable(root: Path, names: tuple[str, ...]) -> Path | None:
    direct_candidates = [root / name for name in names]
    direct_candidates.extend(root / "bin" / name for name in names)
    direct_match = first_existing_file(direct_candidates)
    if direct_match:
        return direct_match

    if not root.is_dir():
        return None

    expected_names = {name.casefold() for name in names}
    for candidate in root.rglob("*"):
        if candidate.is_file() and candidate.name.casefold() in expected_names:
            return candidate
    return None
