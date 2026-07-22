#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(dirname -- "$(dirname -- "$script_dir")")"
colmap_dir="${COLMAP_BUNDLE_DIR:-$workspace_dir/Colmap}"
brush_dir="${BRUSH_BUNDLE_DIR:-$workspace_dir/brush}"
python_executable="${PYTHON_BIN:-$workspace_dir/.venv/bin/python}"

if [[ ! -x "$colmap_dir/bin/colmap" ]]; then
    "$script_dir/prepare_colmap_bundle.sh" "$colmap_dir"
fi

if [[ ! -x "$python_executable" ]]; then
    echo "Build Python not found or not executable: $python_executable" >&2
    echo "Set PYTHON_BIN to the Python environment containing PyInstaller." >&2
    exit 1
fi

if [[ ! -d "$brush_dir" ]]; then
    echo "Brush directory not found: $brush_dir" >&2
    exit 1
fi

export COLMAP_BUNDLE_DIR="$colmap_dir"
export BRUSH_BUNDLE_DIR="$brush_dir"

cd -- "$script_dir"
"$python_executable" -m PyInstaller --noconfirm --clean linux.spec

echo "Linux application folder created: $script_dir/dist/GaussianReconstruction"
echo "Distribute the complete GaussianReconstruction folder."
