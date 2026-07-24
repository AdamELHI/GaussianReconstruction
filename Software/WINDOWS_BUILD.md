# Building the standalone Windows application

PyInstaller must build the application on 64-bit Windows. The expected source
layout is:

```text
GaussianReconstruction/
|-- Brush/
|-- Colmap/
|-- FFmpeg/
|-- Software/
|   |-- controller/
|   |-- model/
|   |-- view/
|   |-- main.py
|   |-- build_windows.ps1
|   `-- windows.spec
|-- Dataset/
|-- Output/
`-- LastReconstruction/
```

`Dataset`, `Output`, and `LastReconstruction` are excluded by `.gitignore`, so
their contents remain local even though the directories are inside the project.
Their common location can still be changed by defining
`GAUSSIAN_RECONSTRUCTION_DATA_ROOT` before starting the application.

## Download Brush

Open the [official Brush releases](https://github.com/ArthurBrussee/brush/releases),
download `brush-app-x86_64-pc-windows-msvc.zip`, and extract it into `Brush`.
The build accepts `brush.exe`, `brush-app.exe`, or `brush_app.exe`, including
inside a nested directory created by the archive.

The official Brush 0.3.0 viewer restricts the scene viewport to the selected
dataset image aspect ratio. For portrait datasets this leaves most of the
window black. To build the patched 0.3.0 executable, install Rust 1.88 or newer
and the Visual Studio C++ build tools, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Software\build_brush_windows.ps1
```

The script applies `Software\patches\brush-v0.3.0-full-viewport.patch` and
places the corrected executable in `Brush\brush_app.exe`. Rust, Cargo, and
Visual Studio Build Tools are only needed to rebuild Brush; final users do not
need them.

Smart App Control must not be in enforcement mode while compiling Brush.
Windows blocks the unsigned Rust build scripts and procedural macro DLLs and
does not provide per-application exceptions. Prefer a dedicated build machine
or CI runner if Smart App Control must remain enabled.

## Download COLMAP

Download COLMAP 4.1.1 or newer and extract a Windows archive from the
[official COLMAP releases](https://github.com/colmap/colmap/releases) into
`Colmap`. Keep the complete extracted directory: `colmap.exe` needs the DLLs
and plugins shipped beside it.

For a package distributed to computers without NVIDIA GPUs, use the `no-cuda`
archive. The application automatically falls back to CPU processing when the
COLMAP bundle has no CUDA support or no compatible NVIDIA GPU is detected.

Use the CUDA archive only for a separate NVIDIA-oriented build. On such a
machine, enable `Use CUDA for COLMAP (NVIDIA only)` in the application settings.
The target computer still needs a compatible NVIDIA GPU and driver. Installing
a CUDA COLMAP build on a computer without CUDA provides no speed benefit and
is less portable.

Brush is separate from this setting: Brush uses WebGPU-compatible technology
and supports NVIDIA, AMD, and Intel hardware.

## Download FFmpeg

Download a 64-bit Windows FFmpeg build containing both `ffmpeg.exe` and
`ffprobe.exe`, then extract it into `FFmpeg`. Nested `bin` directories are
supported. These tools inspect the video field order and create a temporary
progressive copy when an interlaced video is selected.

## Build

Install 64-bit Python 3.12 on the build computer. From PowerShell, enter the
`Software` directory and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

If the dependency folders are elsewhere, pass them explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1 `
  -ColmapDir "C:\Tools\COLMAP" `
  -BrushDir "C:\Tools\Brush" `
  -FfmpegDir "C:\Tools\FFmpeg"
```

The script:

1. validates that the folders contain COLMAP, Brush, FFmpeg, and FFprobe;
2. verifies that a Qt-enabled COLMAP bundle also contains
   `platforms\qwindows.dll`;
3. creates `Software\.venv-windows` with Python 3.12;
4. installs the Python build dependencies;
5. bundles the complete COLMAP, Brush, and FFmpeg directories with the application;
6. verifies that the packaged tool directories exist;
7. creates the application folder and a ZIP release archive.

The final user does not need Python, PyInstaller, COLMAP, Brush, FFmpeg, Rust,
or the Python packages. The executable is located at:

```text
Software\dist\GaussianReconstruction\GaussianReconstruction.exe
```

The distributable archive and its checksum are created at:

```text
Software\dist\GaussianReconstruction-Windows-x64.zip
Software\dist\GaussianReconstruction-Windows-x64.zip.sha256
```

The build prints the archive's exact byte count, decimal MB size, binary MiB
size, and SHA-256 checksum. Services may label MiB as MB, so the displayed
number can be smaller even when the uploaded file is byte-for-byte identical.
Pass `-SkipZip` when only the application folder is needed.

This is a PyInstaller `onedir` build: distribute the complete
`GaussianReconstruction` folder, including its `_internal` directory. The
executable does not contain the approximately 1 GB of dependencies itself and
does not have to extract them into a temporary directory at every launch. The
total size of the distributed folder remains similar because COLMAP, Brush,
Python, Qt, and their dependencies are still required.

`Output` receives exported PLY files. `Dataset` is the initial directory of the
video picker. `LastReconstruction` replaces the former `tmp` directory and
contains the most recent COLMAP/Brush working data when `Keep temporary
directory` is enabled. Their contents are not tracked by Git.

## Not bundled

`splat-transform` remains optional and is not bundled. Reconstruction still
works without it, but optional transparent-point cleanup and PCA alignment are
skipped.

GPU drivers are never bundled. Distribute the licenses required by PyInstaller,
COLMAP, Brush, and their dependencies, and test the executable on a clean
Windows computer before distribution.
