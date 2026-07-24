import os
import shutil
from pathlib import Path


software_dir = Path(SPECPATH)
workspace_dir = software_dir.parent.parent

colmap_dir = Path(
    os.environ.get("COLMAP_BUNDLE_DIR", workspace_dir / "Colmap")
).expanduser().resolve()
brush_root = Path(
    os.environ.get("BRUSH_BUNDLE_DIR", workspace_dir / "brush")
).expanduser().resolve()
ffmpeg_executable = Path(
    os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or ""
).expanduser().resolve()
ffprobe_executable = Path(
    os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or ""
).expanduser().resolve()

if not (colmap_dir / "bin" / "colmap").is_file():
    raise FileNotFoundError(
        f"Bundled COLMAP executable not found: {colmap_dir / 'bin' / 'colmap'}. "
        "Run prepare_colmap_bundle.sh first."
    )

brush_candidates = [
    brush_root / "target" / "release" / "brush",
    brush_root / "target" / "release" / "brush-app",
    brush_root / "target" / "debug" / "brush",
    brush_root / "target" / "debug" / "brush-app",
    brush_root / "brush",
    brush_root / "brush-app",
]
brush_executable = next(
    (candidate for candidate in brush_candidates if candidate.is_file()),
    None,
)
if brush_executable is None:
    raise FileNotFoundError(
        f"No Linux Brush executable was found below: {brush_root}"
    )

if not ffmpeg_executable.is_file():
    raise FileNotFoundError(
        "FFmpeg executable not found. Install it or set FFMPEG_BIN."
    )
if not ffprobe_executable.is_file():
    raise FileNotFoundError(
        "FFprobe executable not found. Install it or set FFPROBE_BIN."
    )

datas = [
    (str(colmap_dir), "tools/colmap"),
    (str(brush_executable), "tools/brush"),
]
binaries = [
    (str(ffmpeg_executable), "tools/ffmpeg"),
    (str(ffprobe_executable), "tools/ffmpeg"),
]

a = Analysis(
    [str(software_dir / "main.py")],
    pathex=[str(software_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GaussianReconstruction",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    contents_directory="_internal",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GaussianReconstruction",
)
