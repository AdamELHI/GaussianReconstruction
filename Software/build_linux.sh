#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname -- "$script_dir")"
colmap_dir="${COLMAP_BUNDLE_DIR:-$project_dir/Colmap}"
python_executable="${PYTHON_BIN:-$project_dir/.venv/bin/python}"
ffmpeg_executable="${FFMPEG_BIN:-$(command -v ffmpeg || true)}"
ffprobe_executable="${FFPROBE_BIN:-$(command -v ffprobe || true)}"

if [[ -n "${BRUSH_BUNDLE_DIR:-}" ]]; then
    brush_dir="$BRUSH_BUNDLE_DIR"
elif [[ -d "$project_dir/Brush" ]]; then
    brush_dir="$project_dir/Brush"
else
    brush_dir="$project_dir/brush"
fi

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
    echo "Set BRUSH_BUNDLE_DIR to the directory containing a Linux Brush build." >&2
    exit 1
fi

brush_executable=""
for candidate in \
    "$brush_dir/target/release/brush" \
    "$brush_dir/target/release/brush-app" \
    "$brush_dir/brush" \
    "$brush_dir/brush-app"
do
    if [[ -x "$candidate" ]]; then
        brush_executable="$candidate"
        break
    fi
done
if [[ -z "$brush_executable" ]]; then
    echo "Brush executable not found below: $brush_dir" >&2
    echo "Build Brush in release mode before packaging the application." >&2
    exit 1
fi

if [[ -z "$ffmpeg_executable" || ! -x "$ffmpeg_executable" ]]; then
    echo "FFmpeg was not found. Install it or set FFMPEG_BIN." >&2
    exit 1
fi
if [[ -z "$ffprobe_executable" || ! -x "$ffprobe_executable" ]]; then
    echo "FFprobe was not found. Install it or set FFPROBE_BIN." >&2
    exit 1
fi

export COLMAP_BUNDLE_DIR="$colmap_dir"
export BRUSH_BUNDLE_DIR="$brush_dir"
export FFMPEG_BIN="$ffmpeg_executable"
export FFPROBE_BIN="$ffprobe_executable"

cd -- "$script_dir"
"$python_executable" -m PyInstaller --noconfirm --clean linux.spec

output_dir="$script_dir/dist/GaussianReconstruction"
output_executable="$output_dir/GaussianReconstruction"
for required_path in \
    "$output_executable" \
    "$output_dir/_internal/tools/colmap/bin/colmap" \
    "$output_dir/_internal/tools/brush/$(basename -- "$brush_executable")" \
    "$output_dir/_internal/tools/ffmpeg/ffmpeg" \
    "$output_dir/_internal/tools/ffmpeg/ffprobe"
do
    if [[ ! -e "$required_path" ]]; then
        echo "The packaged application is incomplete: $required_path is missing." >&2
        exit 1
    fi
done

echo "Linux application folder created: $output_dir"
echo "Executable: $output_executable"
echo "Distribute the complete GaussianReconstruction folder."
