# Building the standalone application

PyInstaller builds are platform-specific: build the Windows package on 64-bit
Windows and the Linux package on 64-bit Linux. In both cases, distribute the
complete generated `GaussianReconstruction` directory, not only its executable.

## Windows

The expected source layout is:

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

### Download Brush

Open the [official Brush releases](https://github.com/ArthurBrussee/brush/releases),
download `brush-app-x86_64-pc-windows-msvc.zip`, and extract it into `Brush`.
The build accepts `brush.exe`, `brush-app.exe`, or `brush_app.exe`, including
inside a nested directory created by the archive.

The prebuilt release is sufficient. Rust, Cargo, and Visual Studio Build Tools
are only required when compiling Brush from source and are not used by this
packaging script.

### Download COLMAP

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

### Download FFmpeg

Download a 64-bit Windows FFmpeg build containing both `ffmpeg.exe` and
`ffprobe.exe`, then extract it into `FFmpeg`. Nested `bin` directories are
supported. These tools inspect the video field order and create a temporary
progressive copy when an interlaced video is selected.

### Build

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

The tool directories must be on the same NTFS volume as the build output.
The script uses hard links when assembling the local package so Windows keeps
the trust metadata required by Smart App Control.

The script:

1. validates that the folders contain COLMAP, Brush, FFmpeg, and FFprobe;
2. verifies that a Qt-enabled COLMAP bundle also contains
   `platforms\qwindows.dll`;
3. creates `Software\.venv-windows` with Python 3.12;
4. installs the Python build dependencies;
5. builds the Python application without processing the external tools;
6. adds the complete COLMAP, Brush, and FFmpeg directories with NTFS hard links;
7. verifies that the packaged COLMAP executable can start;
8. creates the application folder.

The final user does not need Python, PyInstaller, COLMAP, Brush, FFmpeg, Rust,
or the Python packages. The executable is located at:

```text
Software\dist\GaussianReconstruction\GaussianReconstruction.exe
```

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

### Not bundled

`splat-transform` remains optional and is not bundled. Reconstruction still
works without it, but optional transparent-point cleanup and PCA alignment are
skipped.

GPU drivers are never bundled. Distribute the licenses required by PyInstaller,
COLMAP, Brush, and their dependencies, and test the executable on a clean
Windows computer before distribution.

Hard links solve local development builds but do not replace release signing:
copying or archiving the folder creates new files on the destination computer.
Sign release executables and DLLs with a certificate accepted by Windows before
public distribution.

## Linux

Build the Linux application on the oldest Linux distribution that you intend
to support. Linux executables depend on the build system's glibc version and
generally do not run on distributions with an older glibc.

The default source layout is:

```text
GaussianReconstruction/
|-- .venv/
|-- Brush/
|   `-- target/release/brush
|-- Colmap/
|   |-- bin/colmap
|   `-- lib/
|-- Software/
|   |-- controller/
|   |-- model/
|   |-- view/
|   |-- build_linux.sh
|   |-- linux.spec
|   |-- prepare_colmap_bundle.sh
|   `-- main.py
|-- requirements.txt
|-- Dataset/
|-- Output/
`-- LastReconstruction/
```

The dependency paths can be overridden, so Brush, COLMAP, FFmpeg, and the
Python environment do not have to be stored inside the repository.

### Install system dependencies

The build requires Python 3.12 with virtual-environment support, FFmpeg,
FFprobe, and COLMAP. Brush also requires Rust and Cargo when it is built from
source.

On Ubuntu or Debian, install the available equivalents of these packages:

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  clang \
  cmake \
  colmap \
  curl \
  ffmpeg \
  git \
  libclang-dev \
  libssl-dev \
  libudev-dev \
  pkg-config \
  python3.12 \
  python3.12-venv
```

Package names and the packaged Python/COLMAP versions vary by distribution.
COLMAP 4.1.1 or newer is recommended.

### Build Brush

Clone Brush into the project root and compile a release executable:

```bash
git clone https://github.com/ArthurBrussee/brush.git Brush
cd Brush
cargo build --release
cd ..
```

The build script accepts `target/release/brush`,
`target/release/brush-app`, `brush`, or `brush-app` below the Brush directory.
If Brush is stored elsewhere, set `BRUSH_BUNDLE_DIR` when building the
application.

### Prepare the Python environment

From the `GaussianReconstruction` project root, create the environment expected
by the default build configuration and install the pinned dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

An existing Python environment can be used by setting `PYTHON_BIN` to its
Python executable. It must contain PyInstaller and all packages listed in
`requirements.txt`.

### Prepare COLMAP

The application bundle needs the COLMAP executable and its non-system shared
libraries. If `Colmap/bin/colmap` does not exist, `build_linux.sh`
automatically runs `prepare_colmap_bundle.sh`. That helper copies the COLMAP
found in `PATH` and its required libraries into `Colmap`.

The helper rejects a COLMAP executable linked to Intel MKL because copying only
part of an MKL installation does not produce a portable package. Use a COLMAP
build linked to OpenBLAS in that case.

The bundle can also be prepared explicitly:

```bash
cd Software
./prepare_colmap_bundle.sh
cd ..
```

### Build

From the project root, run:

```bash
cd Software
./build_linux.sh
```

To use dependencies in other locations, provide one or more environment
variables:

```bash
COLMAP_BUNDLE_DIR=/opt/colmap-bundle \
BRUSH_BUNDLE_DIR=/opt/brush \
FFMPEG_BIN=/usr/local/bin/ffmpeg \
FFPROBE_BIN=/usr/local/bin/ffprobe \
PYTHON_BIN=/opt/gaussian-build/bin/python \
./build_linux.sh
```

The script:

1. prepares or validates the COLMAP bundle;
2. validates the Brush, FFmpeg, FFprobe, and Python executables;
3. packages the Python application and external tools with PyInstaller;
4. verifies that every required executable exists in the generated directory.

The executable is located at:

```text
Software/dist/GaussianReconstruction/GaussianReconstruction
```

This is a PyInstaller `onedir` build. Distribute the complete
`Software/dist/GaussianReconstruction` directory, including `_internal`.
The target computer does not need Python, PyInstaller, COLMAP, Brush, FFmpeg,
Rust, Cargo, or the Python packages used during the build.

### Not bundled

As on Windows, `splat-transform` and GPU drivers are not bundled. Distribute
the licenses required by PyInstaller, COLMAP, Brush, FFmpeg, and their
dependencies, and test the package on a clean Linux computer representative of
the oldest supported distribution.
