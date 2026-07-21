import os
from pathlib import Path


software_dir = Path(SPECPATH)
colmap_dir = Path(os.environ["COLMAP_BUNDLE_DIR"])
brush_dir = Path(os.environ["BRUSH_BUNDLE_DIR"])
ffmpeg_dir = Path(os.environ["FFMPEG_BUNDLE_DIR"])

if not colmap_dir.is_dir():
    raise FileNotFoundError(f"COLMAP bundle directory not found: {colmap_dir}")
if not brush_dir.is_dir():
    raise FileNotFoundError(f"Brush bundle directory not found: {brush_dir}")
if not ffmpeg_dir.is_dir():
    raise FileNotFoundError(f"FFmpeg bundle directory not found: {ffmpeg_dir}")

ffmpeg_executable = next(ffmpeg_dir.rglob("ffmpeg.exe"), None)
ffprobe_executable = next(ffmpeg_dir.rglob("ffprobe.exe"), None)
if ffmpeg_executable is None or ffprobe_executable is None:
    raise FileNotFoundError(
        f"ffmpeg.exe and ffprobe.exe must both exist below: {ffmpeg_dir}"
    )

datas = [
    (str(colmap_dir), "tools/colmap"),
    (str(brush_dir), "tools/brush"),
    (str(ffmpeg_dir), "tools/ffmpeg"),
]

a = Analysis(
    [str(software_dir / "main.py")],
    pathex=[str(software_dir)],
    binaries=[],
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
