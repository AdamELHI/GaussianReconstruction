

from __future__ import annotations
import math
import os
import re
import signal
import shutil
import sqlite3
import cv2 as cv
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
import numpy as np
from plyfile import PlyData
from scipy.spatial.transform import Rotation
if os.name == "nt":
    import psutil

from model.paths import (
    BUNDLED_TOOLS_DIR,
    FROZEN,
    LAST_RECONSTRUCTION_DIR,
    PROJECT_ROOT,
)


PROCESS_CREATION_FLAGS = (
    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
)
IS_LINUX = sys.platform.startswith("linux")
BRUSH_TRAIN_ITERS_OPTION = (
    "--total-train-iters" if IS_LINUX else "--total-steps"
)
COLMAP_EXTRACTION_OPTIONS = "FeatureExtraction"
COLMAP_MATCHING_OPTIONS = "FeatureMatching"


def tool_path(name: str, required: bool = True) -> str | None:
    env_var = {
        "colmap": "COLMAP_BIN",
        "brush": "BRUSH_BIN",
        "ffmpeg": "FFMPEG_BIN",
        "ffprobe": "FFPROBE_BIN",
        "splat-transform": "SPLAT_TRANSFORM",
    }[name]
    override = os.environ.get(env_var)
    if override:
        executable = Path(override).expanduser()
        if executable.is_file():
            return str(executable)
        raise FileNotFoundError(f"{env_var} does not point to a file: {executable}")

    if os.name == "nt":
        candidates = {
            "colmap": [BUNDLED_TOOLS_DIR / "colmap/bin/colmap.exe", PROJECT_ROOT / "Colmap/bin/colmap.exe"],
            "brush": [BUNDLED_TOOLS_DIR / "brush/brush_app.exe", PROJECT_ROOT / "Brush/brush_app.exe"],
            "ffmpeg": list((BUNDLED_TOOLS_DIR / "ffmpeg").glob("*/bin/ffmpeg.exe")),
            "ffprobe": list((BUNDLED_TOOLS_DIR / "ffmpeg").glob("*/bin/ffprobe.exe")),
            "splat-transform": [],
        }[name]
        system_names = (f"{name}.exe", f"{name}.cmd", name)
    else:
        candidates = {
            "colmap": [BUNDLED_TOOLS_DIR / "colmap/bin/colmap"],
            "brush": [
                BUNDLED_TOOLS_DIR / "brush/brush",
                BUNDLED_TOOLS_DIR / "brush/brush-app",
                PROJECT_ROOT / "Brush/target/release/brush",
                PROJECT_ROOT / "Brush/target/release/brush-app",
                PROJECT_ROOT / "brush/target/release/brush",
                PROJECT_ROOT / "brush/target/release/brush-app",
            ],
            "ffmpeg": [BUNDLED_TOOLS_DIR / "ffmpeg/ffmpeg"],
            "ffprobe": [BUNDLED_TOOLS_DIR / "ffmpeg/ffprobe"],
            "splat-transform": [],
        }[name]
        system_names = (name,)

    discovered = next(
        (str(path.resolve()) for path in candidates if path.is_file()),
        None,
    )
    if discovered is None and FROZEN and name == "colmap":
        raise FileNotFoundError(
            f"Bundled COLMAP executable not found: {candidates[0]}"
        )
    if discovered is None:
        discovered = next(
            (
                path
                for candidate in system_names
                if (path := shutil.which(candidate))
            ),
            None,
        )
    if discovered or not required:
        return discovered
    raise FileNotFoundError(f"{name} executable not found")


def get_memory_info_bytes() -> tuple[int, int]:
    """Return total and currently available physical RAM in bytes."""
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical), int(status.available_physical)
        return 0, 0

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (
            int(page_size * os.sysconf("SC_PHYS_PAGES")),
            int(page_size * os.sysconf("SC_AVPHYS_PAGES")),
        )
    except (AttributeError, OSError, ValueError):
        return 0, 0


def colmap_resource_limits() -> tuple[int, int]:
    total_ram, available_ram = get_memory_info_bytes()
    reserved_ram = max(2 * 1024**3, int(total_ram * 0.20))
    usable_ram = max(0, available_ram - reserved_ram)

    if usable_ram >= 40 * 1024**3:
        max_num_features = 32768
        ram_per_thread = 2 * 1024**3
    elif usable_ram >= 16 * 1024**3:
        max_num_features = 16384
        ram_per_thread = 1024**3
    else:
        max_num_features = 8192
        ram_per_thread = 1024**3

    memory_thread_limit = max(1, usable_ram // ram_per_thread)
    num_threads = max(1, os.cpu_count() or 1)
    num_threads = min(num_threads, memory_thread_limit)
    return max_num_features, num_threads


def sequential_matching_overlap(
    nb_frames: int,
    video_duration_seconds: float,
    matching_window_seconds: float = 5.0,
    overlap_cap: int = 50,
) -> int:
    if nb_frames <= 1:
        return 1

    frame_based_overlap = max(5, math.ceil(nb_frames / 10))

    if not np.isfinite(video_duration_seconds) or video_duration_seconds <= 0:
        temporal_overlap = frame_based_overlap
    else:
        extracted_fps = nb_frames / video_duration_seconds
        temporal_overlap = math.ceil(extracted_fps * matching_window_seconds)

    return min(
        nb_frames - 1,
        overlap_cap,
        max(frame_based_overlap, temporal_overlap),
    )


class PauseManager:
    def __init__(self):
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._lock = threading.Lock()
        self._process = None

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set()

    def pause(self) -> None:
        with self._lock:
            self._resume_event.clear()
            if os.name == "posix":
                self._signal_process(signal.SIGSTOP)
            elif os.name == "nt":
                self._set_windows_process_suspended(True)

    def resume(self) -> None:
        with self._lock:
            if os.name == "posix":
                self._signal_process(signal.SIGCONT)
            elif os.name == "nt":
                self._set_windows_process_suspended(False)
            self._resume_event.set()

    def wait_if_paused(self) -> None:
        self._resume_event.wait()

    def attach_process(self, process) -> None:
        with self._lock:
            self._process = process
            if self.is_paused and os.name == "posix":
                self._signal_process(signal.SIGSTOP)
            elif self.is_paused and os.name == "nt":
                self._set_windows_process_suspended(True)

    def detach_process(self, process) -> None:
        with self._lock:
            if self._process is process:
                self._process = None

    def _signal_process(self, process_signal) -> None:
        process = self._process
        if os.name != "posix" or process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, process_signal)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _set_windows_process_suspended(self, suspended: bool) -> None:
        process = self._process
        if os.name != "nt" or process is None or process.poll() is not None:
            return

        try:
            root_process = psutil.Process(process.pid)
            child_processes = root_process.children(recursive=True)
            processes = child_processes + [root_process]
            if not suspended:
                processes.reverse()
            for child_process in processes:
                try:
                    if suspended:
                        child_process.suspend()
                    else:
                        child_process.resume()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def emit_progress(progress_callback, message: str) -> None:
    if progress_callback:
        progress_callback(message)


class ExternalToolError(RuntimeError):
    pass


def process_environment(
    executable: str,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("QT_PLUGIN_PATH", None)
    env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)

    executable_dir = Path(executable).parent
    root = executable_dir.parent if executable_dir.name == "bin" else executable_dir
    search_paths = [
        path
        for path in (executable_dir, root / "bin", root / "lib")
        if path.is_dir()
    ]
    if search_paths:
        env["PATH"] = os.pathsep.join(
            [*(str(path) for path in search_paths), env.get("PATH", "")]
        )

    library_path = root / "lib"
    if os.name == "posix" and library_path.is_dir():
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [str(library_path), env.get("LD_LIBRARY_PATH", "")]
        )
    elif os.name == "nt":
        qt_plugin = next(
            (
                path
                for path in (
                    root / "platforms/qwindows.dll",
                    root / "plugins/platforms/qwindows.dll",
                    root / "bin/platforms/qwindows.dll",
                )
                if path.is_file()
            ),
            None,
        )
        if qt_plugin:
            env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_plugin.parent)

    if overrides:
        env.update(overrides)
    return env


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path | None = None,
    progress_callback=None,
    user_message: str | None = None,
    done_message: str | None = None,
    output_callback=None,
    pause_controller=None,
    env_overrides: dict[str, str] | None = None,
    heartbeat_message: str | None = None,
    heartbeat_interval_seconds: float = 30.0,
) -> list[str]:
    if pause_controller:
        pause_controller.wait_if_paused()
    if user_message:
        emit_progress(progress_callback, user_message)
    print(f"\n==> {label}", flush=True)
    print("$ " + " ".join(cmd), flush=True)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=process_environment(cmd[0], env_overrides),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            start_new_session=os.name == "posix",
            creationflags=PROCESS_CREATION_FLAGS,
        )
    except OSError as exc:
        emit_progress(
            progress_callback,
            f"{label} could not be started: {exc}",
        )
        raise

    if pause_controller:
        pause_controller.attach_process(process)

    recent_output = deque(maxlen=40)
    ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    heartbeat_stop = threading.Event()
    heartbeat_thread = None
    last_output_at = time.monotonic()
    started_at = last_output_at

    if heartbeat_message and progress_callback:
        def report_heartbeat() -> None:
            while not heartbeat_stop.wait(heartbeat_interval_seconds):
                if pause_controller and pause_controller.is_paused:
                    continue
                if time.monotonic() - last_output_at < heartbeat_interval_seconds:
                    continue

                elapsed_seconds = max(0, int(time.monotonic() - started_at))
                hours, remainder = divmod(elapsed_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                emit_progress(
                    progress_callback,
                    f"{heartbeat_message} "
                    f"(elapsed {hours:02d}:{minutes:02d}:{seconds:02d}).",
                )

        heartbeat_thread = threading.Thread(
            target=report_heartbeat,
            name=f"{label}-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()

    try:
        assert process.stdout is not None
        for line in process.stdout:
            last_output_at = time.monotonic()
            print(line, end="", flush=True)
            cleaned_line = ansi_escape.sub("", line)
            for output_line in cleaned_line.replace("\r", "\n").splitlines():
                output_line = output_line.strip()
                if output_line:
                    recent_output.append(output_line)
            if output_callback is not None:
                output_callback(line)
        return_code = process.wait()
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
        if pause_controller:
            pause_controller.detach_process(process)
    if return_code != 0:
        output_tail = "\n".join(recent_output).strip()
        message = f"{label} failed with exit code {return_code}."
        if output_tail:
            message += f"\nLast messages from {label}:\n{output_tail[-6000:]}"
        raise ExternalToolError(message)
    if done_message:
        emit_progress(progress_callback, done_message)
    return list(recent_output)


def indexed_colmap_progress(progress_callback, stage: str, marker: str):
    if progress_callback is None:
        return None

    pattern = re.compile(rf"{re.escape(marker)}\s+\[(\d+)/(\d+)\]")

    def report(line: str) -> None:
        match = pattern.search(line)
        if match:
            current, total = match.groups()
            emit_progress(
                progress_callback,
                f"{stage}: {current}/{total} frames processed.",
            )

    return report


def mapping_progress(progress_callback, total_frames: int):
    if progress_callback is None:
        return None

    registering_pattern = re.compile(r"Registering image #(\d+)")
    dealt_with: set[str] = set()

    def report(line: str) -> None:
        match = registering_pattern.search(line)
        if match:
            dealt_with.add(match.group(1))
            emit_progress(
                progress_callback,
                f"Mapping: {len(dealt_with)}/{total_frames} frames dealt with.",
            )

    return report


def tool_output_progress(progress_callback, stage: str):
    if progress_callback is None:
        return None

    ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    previous_line = None

    def report(line: str) -> None:
        nonlocal previous_line
        cleaned_line = ansi_escape.sub("", line)
        for output_line in cleaned_line.replace("\r", "\n").splitlines():
            output_line = output_line.strip()
            if not output_line or output_line == previous_line:
                continue
            previous_line = output_line
            emit_progress(progress_callback, f"{stage}: {output_line}")

    return report


def brush_training_progress(progress_callback, total_steps: int):
    if progress_callback is None:
        return None

    ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    step_pattern = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
    logged_step_pattern = re.compile(r"\b(?:refine|eval)\s+iter\s+(\d+)\b", re.IGNORECASE)
    report_interval = max(1, total_steps // 100)
    last_reported_step = -report_interval
    previous_line = None

    def report(line: str) -> None:
        nonlocal last_reported_step, previous_line
        cleaned_line = ansi_escape.sub("", line)
        for output_line in cleaned_line.replace("\r", "\n").splitlines():
            output_line = output_line.strip()
            if not output_line:
                continue

            step_match = step_pattern.search(output_line)
            if step_match and int(step_match.group(2)) == total_steps:
                current_step = int(step_match.group(1))
            else:
                logged_step_match = logged_step_pattern.search(output_line)
                current_step = (
                    int(logged_step_match.group(1))
                    if logged_step_match
                    else None
                )

            if current_step is not None:
                if (
                    current_step != total_steps
                    and current_step < last_reported_step + report_interval
                ):
                    continue
                last_reported_step = current_step
                percentage = min(100, round(current_step * 100 / total_steps))
                emit_progress(
                    progress_callback,
                    f"Brush training: {current_step}/{total_steps} steps "
                    f"({percentage}%).",
                )
                continue

            if output_line != previous_line:
                previous_line = output_line
                emit_progress(progress_callback, f"Brush: {output_line}")

    return report


def command_output(command: list[str], timeout: int = 10) -> str | None:
    try:
        result = subprocess.run(
            command,
            env=process_environment(command[0]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=PROCESS_CREATION_FLAGS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def probe_video_field_order(input_path: Path) -> str:
    output = command_output(
        [
            tool_path("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=field_order",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        timeout=30,
    )
    if output is None:
        raise ExternalToolError("FFprobe could not inspect the video field order.")

    for line in output.splitlines():
        field_order = line.strip().lower()
        if field_order:
            return field_order
    return "unknown"


def normalize_video_if_interlaced(
    input_path: Path,
    tmp_dir: Path,
    progress_callback=None,
    pause_controller=None,
) -> Path:
    field_order = probe_video_field_order(input_path)
    field_order_message = f"Video field order detected: {field_order}."
    print(field_order_message)
    emit_progress(progress_callback, field_order_message)

    if field_order not in ("tt", "bb", "tb", "bt"):
        return input_path

    normalized_path = tmp_dir / "progressive_input.mp4"
    run_step(
        "ffmpeg video normalization",
        [
            tool_path("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-vf",
            "bwdif=mode=send_frame:parity=auto:deint=all,format=yuv420p",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(normalized_path),
        ],
        progress_callback=progress_callback,
        user_message=(
            "The video is not progressive. Creating a temporary progressive "
            "copy before extracting frames."
        ),
        done_message="The temporary progressive video is ready.",
        output_callback=tool_output_progress(
            progress_callback,
            "Video normalization",
        ),
        pause_controller=pause_controller,
    )

    if not normalized_path.is_file() or normalized_path.stat().st_size == 0:
        raise ExternalToolError(
            "FFmpeg did not create the temporary progressive video."
        )
    return normalized_path


def colmap_supports_cuda(colmap_executable: str) -> bool:
    general_help = command_output([colmap_executable, "-h"])
    if general_help and "without cuda" in general_help.lower():
        return False
    if general_help and "with cuda" in general_help.lower():
        return True

    feature_help = command_output(
        [colmap_executable, "feature_extractor", "-h"]
    )
    return (
        feature_help is not None
        and f"--{COLMAP_EXTRACTION_OPTIONS}.use_gpu" in feature_help
    )


def report_colmap_identity(colmap_executable: str, progress_callback=None) -> None:
    resolved_path = Path(colmap_executable).resolve()
    help_output = command_output([str(resolved_path), "-h"])
    version_line = next(
        (
            line.strip()
            for line in (help_output or "").splitlines()
            if "colmap" in line.lower() and any(char.isdigit() for char in line)
        ),
        "version unavailable",
    )
    message = f"COLMAP executable: {resolved_path} ({version_line})."
    print(message)
    emit_progress(progress_callback, message)


def cuda_gpu_available() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False

    output = command_output([nvidia_smi, "-L"])
    return output is not None and any(
        line.strip().startswith("GPU ")
        for line in output.splitlines()
    )


def available_gpu_memory_bytes() -> int:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return 0

    output = command_output(
        [
            nvidia_smi,
            "--query-gpu=memory.free",
            "--format=csv,noheader,nounits",
        ]
    )
    if output is None:
        return 0

    free_memory_mib = []
    for line in output.splitlines():
        try:
            free_memory_mib.append(int(line.strip()))
        except ValueError:
            continue

    if not free_memory_mib:
        return 0

    # COLMAP uses every selected GPU, so use the smallest available capacity.
    return min(free_memory_mib) * 1024**2


def colmap_gpu_match_limit(max_num_matches: int) -> tuple[int, int]:
    available_vram = available_gpu_memory_bytes()
    if available_vram >= 16 * 1024**3:
        gpu_limit = 32768
    elif available_vram >= 5 * 1024**3:
        gpu_limit = 16384
    else:
        gpu_limit = 8192
    return min(max_num_matches, gpu_limit), available_vram


def configure_colmap_gpu(
    colmap_executable: str,
    gpu_requested: bool,
    progress_callback=None,
) -> bool:
    if not gpu_requested:
        message = "COLMAP GPU acceleration is disabled; using the CPU."
        enabled = False
    elif not colmap_supports_cuda(colmap_executable):
        message = (
            "The bundled COLMAP does not report CUDA support; "
            "feature extraction and matching will use the CPU."
        )
        enabled = False
    elif not cuda_gpu_available():
        message = (
            "COLMAP supports CUDA, but no compatible NVIDIA GPU was detected; "
            "feature extraction and matching will use the CPU."
        )
        enabled = False
    else:
        message = (
            "COLMAP CUDA support detected; feature extraction and matching "
            "will use the GPU."
        )
        enabled = True
    print(message)
    emit_progress(progress_callback, message)
    return enabled


def colmap_database_match_count(database_path: Path) -> int:
    try:
        with sqlite3.connect(database_path) as database:
            row = database.execute(
                "SELECT COUNT(*) FROM two_view_geometries WHERE rows > 0"
            ).fetchone()
    except sqlite3.Error as exc:
        raise ExternalToolError(
            f"COLMAP matching results could not be verified: {exc}"
        ) from exc
    return int(row[0]) if row else 0


def align_ply(ply_path: Path, progress_callback=None, pause_controller=None) -> None:
    """PCA-align the exported splat using splat-transform."""
    if pause_controller:
        pause_controller.wait_if_paused()

    vertex = PlyData.read(str(ply_path))["vertex"]
    points = np.column_stack(
        tuple(
            np.asarray(vertex[axis], dtype=np.float64)
            for axis in ("x", "y", "z")
        )
    )
    if points.size == 0:
        return
    if len(points) < 2:
        raise ValueError("At least two points are required for PCA alignment.")

    mean = points.mean(axis=0)
    centered_points = points - mean
    _, eigenvectors = np.linalg.eigh(
        (centered_points.T @ centered_points) / (len(points) - 1)
    )
    components = eigenvectors[:, ::-1].T
    if pause_controller:
        pause_controller.wait_if_paused()
    R = np.asarray(components, dtype=np.float64)
    if np.linalg.det(R) < 0:
        R[2, :] *= -1.0
    t = -R @ mean
    euler_deg = Rotation.from_matrix(R).as_euler("xyz", degrees=True)
    ex, ey, ez = (float(x) for x in euler_deg)
    tx, ty, tz = (float(x) for x in t)

    fd, tmp_name = tempfile.mkstemp(suffix=".ply", dir=str(ply_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        run_step(
            "splat-transform (PCA align)",
            [
                tool_path("splat-transform"),
                str(ply_path),
                f"--rotate={ex},{ey},{ez}",
                f"--translate={tx},{ty},{tz}",
                str(tmp_path),
                "-w",
            ],
            progress_callback=progress_callback,
            user_message="Centring the 3D model to make it easier to view.",
            done_message="Centred 3D model .",
            pause_controller=pause_controller,
        )
        os.replace(tmp_path, ply_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()





def main(
    input_file,
    output_file,
    frame_rate=5.0,
    start_time=None,
    end_time=None,
    total_train_iters=10000,
    use_gpu=True,
    keep_temp=False,
    skip_align=False,
    is_loading=False,
    progress_callback=None,
    pause_controller=None,
) -> int:
    if not np.isfinite(frame_rate) or frame_rate <= 0:
        raise ValueError("Frame rate must be greater than zero.")
    if pause_controller:
        pause_controller.wait_if_paused()

    input_path = Path(input_file).expanduser()
    output_path = Path(output_file).expanduser()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_dir = output_path.parent
    output_name = output_path.name
    output_dir.mkdir(parents=True, exist_ok=True)
    emit_progress(
        progress_callback,
        "Checking the video and preparing the output folder.",
    )
    tmp_dir = LAST_RECONSTRUCTION_DIR
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    images_dir = tmp_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    emit_progress(
        progress_callback,
        "Setting up the temporary folder for source images.",
    )

    emit_progress(
        progress_callback,
        "Checking the dependencies required for the reconstruction.",
    )
    brush = tool_path("brush")
    brush_working_dir = Path(tempfile.gettempdir()) / "gr-brush"
    (brush_working_dir / "target").mkdir(parents=True, exist_ok=True)
    if is_loading :
        brush_args = [
            brush,
            str(input_path),
            "--with-viewer"
        ]
        run_step(
            "brush",
            brush_args,
            progress_callback=progress_callback,
            user_message="Opening the 3D file in the viewer.",
            done_message="Visualization is completed.",
            output_callback=tool_output_progress(progress_callback, "Brush"),
            pause_controller=pause_controller,
            cwd=brush_working_dir,
        )
    else :
        colmap = tool_path("colmap")
        report_colmap_identity(colmap, progress_callback)
        use_colmap_gpu = configure_colmap_gpu(
            colmap,
            use_gpu,
            progress_callback,
        )
        print("The next steps in the implementation process are :")
        print("  1. Extracting frames from video (ffmpeg)")
        print("  2. COLMAP feature extraction")
        print("  3. COLMAP sequential matching")
        print("  4. COLMAP mapper")
        print("  5. Brush training/export")
        print("  6. Optional splat-transform cleanup/alignment")

        processing_input_path = normalize_video_if_interlaced(
            input_path,
            tmp_dir,
            progress_callback=progress_callback,
            pause_controller=pause_controller,
        )

        video_capture = cv.VideoCapture(str(processing_input_path))
        if not video_capture.isOpened():
            raise RuntimeError(f"Could not open video: {processing_input_path}")

        nb_frame = 0
        nb_saved = 0

        fps = video_capture.get(cv.CAP_PROP_FPS)
        if not np.isfinite(fps) or fps <= 0:
            video_capture.release()
            raise RuntimeError("Could not determine a valid video frame rate.")

        end_frame = int(video_capture.get(cv.CAP_PROP_FRAME_COUNT))

        if start_time:
            h, m, sec = map(int, start_time.split(":"))
            nb_frame = int((h * 3600 + m * 60 + sec) * fps)

        if end_time:
            h, m, sec = map(int, end_time.split(":"))
            end_frame = min(
                end_frame,
                int((h * 3600 + m * 60 + sec) * fps),
            )

        if nb_frame >= end_frame:
            video_capture.release()
            raise RuntimeError("The selected video range does not contain any frames.")

        base_interval = max(1.0, fps / frame_rate)
        snapshot_every = max(1, round(base_interval))
        next_snapshot = nb_frame
        video_capture.set(cv.CAP_PROP_POS_FRAMES, nb_frame)
        score_mean = None

        frame_count = end_frame - nb_frame
        progress_interval = max(1, frame_count // 100)
        processed_count = 0
        while nb_frame < end_frame:
            if pause_controller:
                pause_controller.wait_if_paused()
            success, image = video_capture.read()
            if not success:
                break
            processed_count += 1

            if nb_frame >= next_snapshot:
                gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
                laplacian = cv.Laplacian(gray, cv.CV_16S)
                _, laplacian_stddev = cv.meanStdDev(laplacian)
                sharpness = float(laplacian_stddev[0, 0] ** 2)

                image_path = images_dir / f"frame_{nb_saved:05d}.jpg"
                if not cv.imwrite(str(image_path), image):
                    video_capture.release()
                    raise RuntimeError(f"Could not write extracted frame: {image_path}")
                nb_saved += 1
                if score_mean is None:
                    score_mean = sharpness
                    target_interval = snapshot_every
                else:
                    sharpness_ratio = sharpness / max(score_mean, 1e-6)
                    sharpness_ratio = min(1.5, max(0.5, sharpness_ratio))
                    target_interval = max(
                        1,
                        round(base_interval * sharpness_ratio),
                    )
                    score_mean += 0.15 * (sharpness - score_mean)

                snapshot_every = max(
                    1,
                    round((snapshot_every + target_interval) / 2),
                )
                print(
                    f"Frame {nb_frame}: sharpness={sharpness:.2f}, "
                    f"reference={score_mean:.2f}, interval={snapshot_every}"
                )
                next_snapshot = nb_frame + snapshot_every

            nb_frame += 1
            if (
                processed_count % progress_interval == 0
                or processed_count == frame_count
            ):
                message = (
                    f"Extracting frames: {processed_count}/{frame_count} "
                    "video frames processed."
                )
                print(message)
                emit_progress(progress_callback, message)

        video_capture.release()
        video_duration_seconds = processed_count / fps
        print(f"{nb_saved} images extracted")


        max_num_features, num_threads = colmap_resource_limits()
        print(
            "COLMAP resource limits: "
            f"max features/matches={max_num_features}, threads={num_threads}"
        )

        feature_args = [
            colmap,
            "feature_extractor",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--image_path",
            str(images_dir),
            "--ImageReader.single_camera",
            "1",
            "--ImageReader.camera_model",
            "SIMPLE_RADIAL",
            "--SiftExtraction.estimate_affine_shape",
            "1",
            "--SiftExtraction.domain_size_pooling",
            "1",
            "--SiftExtraction.peak_threshold", "0.003",
            "--SiftExtraction.max_num_features",
            str(max_num_features),
            f"--{COLMAP_EXTRACTION_OPTIONS}.num_threads",
            str(num_threads)
        ]
        if use_colmap_gpu:
            feature_args.extend([f"--{COLMAP_EXTRACTION_OPTIONS}.use_gpu", "1"])
        else:
            feature_args.extend([f"--{COLMAP_EXTRACTION_OPTIONS}.use_gpu", "0"])

        run_step(
            "feature_extractor",
            feature_args,
            progress_callback=progress_callback,
            user_message=(
                "Searching for recognizable points in each image "
                f"using {'the CUDA GPU' if use_colmap_gpu else 'the CPU'}."
            ),
            done_message="Important points detected in the images.",
            output_callback=indexed_colmap_progress(
                progress_callback,
                "Feature extraction",
                "Processed file",
            ),
            pause_controller=pause_controller,
        )


        max_num_matches, num_threads = colmap_resource_limits()
        max_num_matches = min(max_num_features, max_num_matches)
        if use_colmap_gpu:
            max_num_matches, available_vram = colmap_gpu_match_limit(
                max_num_matches
            )
            print(
                "COLMAP GPU matching limit: "
                f"{max_num_matches} matches with "
                f"{available_vram / 1024**3:.1f} GiB of available VRAM"
            )
        matching_overlap = sequential_matching_overlap(
            nb_saved,
            video_duration_seconds,
        )
        print(
            "COLMAP matching limits: "
            f"max matches={max_num_matches}, "
            f"threads={num_threads}, overlap={matching_overlap}"
        )

        matcher_args = [
            colmap,
            "sequential_matcher",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--SequentialMatching.overlap",
            str(matching_overlap),
            f"--{COLMAP_MATCHING_OPTIONS}.max_num_matches", str(max_num_matches),
            f"--{COLMAP_MATCHING_OPTIONS}.guided_matching", "1",
            f"--{COLMAP_MATCHING_OPTIONS}.num_threads", str(num_threads),
            
        ]

        if use_colmap_gpu:
            matcher_args.extend([f"--{COLMAP_MATCHING_OPTIONS}.use_gpu", "1"])
        else:
            matcher_args.extend([f"--{COLMAP_MATCHING_OPTIONS}.use_gpu", "0"])
        
        
        matcher_output = run_step(
            "sequential_matcher",
            matcher_args,
            progress_callback=progress_callback,
            user_message=(
                "Comparing images to find camera movement "
                f"using {'the CUDA GPU' if use_colmap_gpu else 'the CPU'}."
            ),
            output_callback=indexed_colmap_progress(
                progress_callback,
                "Matching",
                "Matching image",
            ),
            pause_controller=pause_controller,
        )

        match_count = colmap_database_match_count(tmp_dir / "database.db")
        if match_count == 0:
            matching_error = (
                "COLMAP matching failed: no image pairs with valid matches "
                "were written to the database."
            )
            output_tail = "\n".join(matcher_output).strip()
            if output_tail:
                matching_error += (
                    "\nLast messages from sequential_matcher:\n"
                    f"{output_tail[-6000:]}"
                )
            raise ExternalToolError(matching_error)
        emit_progress(progress_callback, "Images linked together.")

        sparse_dir = tmp_dir / "sparse"
        sparse_dir.mkdir(parents=True, exist_ok=True)

        _, num_threads = colmap_resource_limits()
        print(f"COLMAP mapper limits: threads={num_threads}")

        mapper_args = [
            colmap,
            "mapper",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--image_path",
            str(images_dir),
            "--output_path",
            str(sparse_dir),
            "--Mapper.num_threads",
            str(num_threads),
            "--Mapper.max_model_overlap",
            "30",
            "--Mapper.ba_global_max_refinements","20",
            "--Mapper.init_min_num_inliers", "50",
            "--Mapper.min_num_matches", "10",
            "--Mapper.tri_min_angle", "0.5",
            "--Mapper.ba_global_max_num_iterations", "15",
            "--Mapper.ba_local_max_num_iterations","10",
            "--Mapper.filter_max_reproj_error", "2",
            "--Mapper.max_reg_trials", "10",
        ]
        run_step(
            "mapper",
            mapper_args,
            progress_callback=progress_callback,
            user_message="Construction of an initial 3D structure from the images.",
            done_message="Basic 3D structure constructed.",
            output_callback=mapping_progress(progress_callback, nb_saved),
            pause_controller=pause_controller,
        )

        # Brush training (gaussian) and export

        brush_output_dir = tmp_dir / "brush_output"
        brush_output_dir.mkdir(parents=True, exist_ok=True)
        brush_ply_path = brush_output_dir / output_name
        brush_args = [
            brush,
            str(tmp_dir),
            BRUSH_TRAIN_ITERS_OPTION,
            str(total_train_iters),
            "--export-every",
            str(total_train_iters),
            "--export-path",
            str(brush_output_dir),
            "--export-name",
            output_name,
        ]
        brush_output = run_step(
            "brush",
            brush_args,
            progress_callback=progress_callback,
            user_message="Training the 3D model with Brush. This step can take a long time.",
            done_message="Brush has exported the first 3D file.",
            output_callback=brush_training_progress(
                progress_callback,
                total_train_iters,
            ),
            pause_controller=pause_controller,
            cwd=brush_working_dir,
            env_overrides={
                "RUST_LOG": "brush_cli=info,brush_app=info",
                "RUST_BACKTRACE": "1",
            },
            heartbeat_message="Brush training is still running",
        )
        if not brush_ply_path.is_file():
            output_tail = "\n".join(brush_output).strip()
            raise ExternalToolError(
                "Brush stopped without producing a PLY file."
                + (
                    f"\nLast messages from Brush:\n{output_tail[-6000:]}"
                    if output_tail
                    else ""
                )
            )
        os.replace(brush_ply_path, output_path)
        ply_path = output_path
        splat_transform = tool_path("splat-transform", required=False)
        if splat_transform:
            temp_ply = tempfile.NamedTemporaryFile(suffix=".ply", dir=str(output_dir), delete=False)
            temp_ply.close()
            temp_ply_path = Path(temp_ply.name)
            run_step(
                "splat-transform clean transparents",
                [
                    splat_transform,
                    str(ply_path),
                    "-V",
                    "opacity,gt,0.01",
                    str(temp_ply_path),
                    "-w",
                ],
                progress_callback=progress_callback,
                user_message="Cleaning transparent points in the 3D file.",
                done_message="3D file cleaned.",
                pause_controller=pause_controller,
            )
            os.replace(temp_ply_path, ply_path)
        else:
            emit_progress(
                progress_callback,
                "Optional cleaning is ignored; the relevant tool is not available.",
            )

        if not skip_align and splat_transform:
            align_ply(ply_path, progress_callback, pause_controller)
        elif skip_align:
            emit_progress(
                progress_callback,
                "Final alignment is skipped according to the chosen parameters.",
            )

        if not keep_temp:
            if pause_controller:
                pause_controller.wait_if_paused()
            emit_progress(progress_callback, "Deleting temporary files.")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)

        print(f"Done: {ply_path}", flush=True)
        emit_progress(
            progress_callback,
            "Processing completed. Opening the 3D model in Brush.",
        )
        try:
            run_step(
                "brush viewer",
                [brush, str(ply_path), "--with-viewer"],
                progress_callback=progress_callback,
                done_message="Brush viewer closed.",
                output_callback=tool_output_progress(progress_callback, "Brush"),
                pause_controller=pause_controller,
                cwd=brush_working_dir,
            )
        except (OSError, ExternalToolError) as exc:
            emit_progress(
                progress_callback,
                f"The 3D file was created, but Brush could not open it: {exc}",
            )
        return 0


def run(
    inputfile,
    outputfile,
    fps,
    starttime=None,
    endtime=None,
    totaltrainiters=10000,
    usegpu=True,
    keeptemp=False,
    skipalign=False,
    progress_callback=None,
    pause_controller=None,
):
    return main(
        inputfile,
        outputfile,
        frame_rate=fps,
        start_time=starttime,
        end_time=endtime,
        total_train_iters=totaltrainiters,
        use_gpu=usegpu,
        keep_temp=keeptemp,
        skip_align=skipalign,
        progress_callback=progress_callback,
        pause_controller=pause_controller,
    )


def load(inputfile, progress_callback=None):
    return main(
        inputfile,
        inputfile,
        is_loading=True,
        progress_callback=progress_callback,
    )


