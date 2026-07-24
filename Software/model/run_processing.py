

from __future__ import annotations
import argparse
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
from collections import deque
from pathlib import Path
import numpy as np
from plyfile import PlyData
from scipy.spatial.transform import Rotation


PROJECT_DIR = Path(__file__).resolve().parents[2] #.../GaussianReconstruction

WORKSPACE_DIR = PROJECT_DIR.parent 
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BUNDLED_TOOLS_DIR = Path(sys._MEIPASS) / "tools" # .../GaussianReconstruction/_internal/tools
else:
    BUNDLED_TOOLS_DIR = None


def find_tool(root: Path, candidates: tuple[Path, ...]) -> str | None:
    for relative_path in candidates:
        executable = root / relative_path
        if executable.is_file() and os.access(executable, os.X_OK):
            return str(executable)
    return None


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
        memory_info = {}
        with open("/proc/meminfo", encoding="utf-8") as file:
            for line in file:
                name, value = line.split(":", 1)
                memory_info[name] = int(value.strip().split()[0]) * 1024
        total_ram = memory_info.get("MemTotal", 0)
        available_ram = memory_info.get("MemAvailable", 0)
        if total_ram and available_ram:
            return total_ram, available_ram
    except (FileNotFoundError, OSError, ValueError, IndexError):
        pass

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_ram = int(page_size * os.sysconf("SC_PHYS_PAGES"))
        available_ram = int(page_size * os.sysconf("SC_AVPHYS_PAGES"))
        return total_ram, available_ram
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

    def resume(self) -> None:
        with self._lock:
            if os.name == "posix":
                self._signal_process(signal.SIGCONT)
            self._resume_event.set()

    def wait_if_paused(self) -> None:
        self._resume_event.wait()

    def attach_process(self, process) -> None:
        with self._lock:
            self._process = process
            if self.is_paused and os.name == "posix":
                self._signal_process(signal.SIGSTOP)

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


def emit_progress(progress_callback, message: str) -> None:
    if progress_callback:
        progress_callback(message)


class ExternalToolError(RuntimeError):
    pass


def external_tool_error_message(
    label: str,
    return_code: int,
    output_lines,
) -> str:
    return_description = f"exit code {return_code}"
    if return_code < 0 and os.name == "posix":
        try:
            return_description = (
                f"signal {signal.Signals(-return_code).name} ({return_code})"
            )
        except ValueError:
            pass

    message = f"{label} failed with {return_description}."
    output_tail = "\n".join(output_lines).strip()
    if output_tail:
        message += f"\nLast messages from {label}:\n{output_tail[-6000:]}"
    else:
        message += f"\n{label} did not provide an error message."
    return message


def finalize_brush_output(
    brush_ply_path: Path,
    output_path: Path,
    brush_output,
) -> Path:
    if not brush_ply_path.is_file():
        brush_error = (
            "Brush stopped before the training was completed and did not "
            "produce a new PLY file. The Brush window may have crashed."
        )
        output_tail = "\n".join(brush_output).strip()
        if output_tail:
            brush_error += f"\nLast messages from Brush:\n{output_tail[-6000:]}"
        raise ExternalToolError(brush_error)

    os.replace(brush_ply_path, output_path)
    return output_path


def external_tool_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("QT_PLUGIN_PATH", None)
    env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)

    search_paths = []
    library_paths = []
    if BUNDLED_TOOLS_DIR is not None:
        search_paths.extend(
            [
                BUNDLED_TOOLS_DIR / "colmap" / "bin",
                BUNDLED_TOOLS_DIR / "brush",
                BUNDLED_TOOLS_DIR / "ffmpeg",
            ]
        )
        library_paths.append(BUNDLED_TOOLS_DIR / "colmap" / "lib")

    existing_search_paths = [str(path) for path in search_paths if path.is_dir()]
    if existing_search_paths:
        env["PATH"] = os.pathsep.join(
            existing_search_paths + [env.get("PATH", "")]
        )

    existing_library_paths = [str(path) for path in library_paths if path.is_dir()]
    if existing_library_paths:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            existing_library_paths + [env.get("LD_LIBRARY_PATH", "")]
        )

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
) -> list[str]:
    if pause_controller:
        pause_controller.wait_if_paused()
    if user_message:
        emit_progress(progress_callback, user_message)
    print(f"\n==> {label}", flush=True)
    print("$ " + " ".join(cmd), flush=True)
    env = external_tool_environment()

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            start_new_session=os.name == "posix",
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
    try:
        assert process.stdout is not None
        for line in process.stdout:
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
        if pause_controller:
            pause_controller.detach_process(process)

    if return_code != 0:
        raise ExternalToolError(
            external_tool_error_message(
                label,
                return_code,
                recent_output,
            )
        )
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


def resolve_executable(names: list[str], env_var: str | None = None) -> str:
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(f"Could not find any of {names}")


def resolve_ffmpeg_tool(name: str) -> str:
    env_var = f"{name.upper()}_BIN"
    override = os.environ.get(env_var)
    if override:
        executable = Path(override).expanduser()
        if executable.is_file() and os.access(executable, os.X_OK):
            return str(executable)
        raise FileNotFoundError(
            f"{env_var} does not point to an executable file: {executable}"
        )

    if BUNDLED_TOOLS_DIR is not None:
        bundled = find_tool(
            BUNDLED_TOOLS_DIR / "ffmpeg",
            (Path(name), Path(f"{name}.exe")),
        )
        if bundled:
            return bundled

    return resolve_executable([name, f"{name}.exe"])


def probe_video_field_order(input_path: Path) -> str:
    ffprobe = resolve_ffmpeg_tool("ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe,
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
            env=external_tool_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExternalToolError(
            f"Could not inspect the video field order with FFprobe: {exc}"
        ) from exc

    if result.returncode != 0:
        raise ExternalToolError(
            external_tool_error_message(
                "ffprobe",
                result.returncode,
                result.stdout.splitlines(),
            )
        )

    for line in result.stdout.splitlines():
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

    interlaced_orders = {"tt", "bb", "tb", "bt"}

    if field_order not in interlaced_orders :
        return input_path
    
    normalized_path = tmp_dir / "progressive_input.mp4"
    run_step(
        "ffmpeg video normalization",
        [
            resolve_ffmpeg_tool("ffmpeg"),
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


def resolve_colmap() -> str:
    override = os.environ.get("COLMAP_BIN")
    if override:
        return override

    if BUNDLED_TOOLS_DIR is not None:
        bundled = find_tool(
            BUNDLED_TOOLS_DIR / "colmap",
            (Path("bin/colmap"), Path("colmap")),
        )
        if bundled:
            return bundled

    external = find_tool(
        WORKSPACE_DIR / "Colmap",
        (Path("bin/colmap"), Path("colmap")),
    )
    if external:
        return external

    return resolve_executable(["colmap"])


def colmap_supports_cuda(colmap_executable: str) -> bool:
    try:
        result = subprocess.run(
            [colmap_executable, "-h"],
            env=external_tool_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    version_lines = "\n".join(result.stdout.splitlines()[:5]).lower()
    if "without cuda" in version_lines:
        return False
    return "with cuda" in version_lines


def cuda_gpu_available() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False

    try:
        result = subprocess.run(
            [nvidia_smi, "-L"],
            env=external_tool_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0 and any(
        line.strip().startswith("GPU ")
        for line in result.stdout.splitlines()
    )


def available_gpu_memory_bytes() -> int:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return 0

    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            env=external_tool_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0

    if result.returncode != 0:
        return 0

    free_memory_mib = []
    for line in result.stdout.splitlines():
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
        print(message)
        emit_progress(progress_callback, message)
        return False

    if not colmap_supports_cuda(colmap_executable):
        message = (
            "The bundled COLMAP does not report CUDA support; "
            "feature extraction and matching will use the CPU."
        )
        print(message)
        emit_progress(progress_callback, message)
        return False

    if not cuda_gpu_available():
        message = (
            "COLMAP supports CUDA, but no compatible NVIDIA GPU was detected; "
            "feature extraction and matching will use the CPU."
        )
        print(message)
        emit_progress(progress_callback, message)
        return False

    message = (
        "COLMAP CUDA support detected; feature extraction and matching "
        "will use the GPU."
    )
    print(message)
    emit_progress(progress_callback, message)
    return True


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


def resolve_brush(progress_callback=None) -> str:
    override = os.environ.get("BRUSH_BIN")
    if override and Path(override).expanduser().is_file():
        return str(Path(override).expanduser())

    if BUNDLED_TOOLS_DIR is not None:
        bundled = find_tool(
            BUNDLED_TOOLS_DIR / "brush",
            (Path("brush"), Path("brush-app")),
        )
        if bundled:
            return bundled

    external = find_tool(
        WORKSPACE_DIR / "brush",
        (
            Path("target/release/brush"),
            Path("target/release/brush-app"),
            Path("target/debug/brush"),
            Path("target/debug/brush-app"),
        ),
    )
    if external:
        return external

    discovered = shutil.which("brush") or shutil.which("brush-app")
    if discovered:
        return discovered
    raise FileNotFoundError("Brush executable not found")




def splat_transform_executable() -> str:
    """Resolve ``splat-transform`` for ``subprocess`` (Windows needs ``.cmd`` path)."""
    override = os.environ.get("SPLAT_TRANSFORM")
    if override:
        return override
    return resolve_executable(["splat-transform", "splat-transform.cmd", "splat-transform.exe"])


def load_ply_point_cloud(ply_path: Path) -> np.ndarray:
    """Load vertex x,y,z from a .ply as ``(N, 3)`` float64 (uses ``plyfile``)."""
    path = ply_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    ply = PlyData.read(str(path))
    vertex = ply["vertex"]
    x = np.asarray(vertex["x"], dtype=np.float64)
    y = np.asarray(vertex["y"], dtype=np.float64)
    z = np.asarray(vertex["z"], dtype=np.float64)
    return np.column_stack((x, y, z))


def pca_xyz(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Covariance PCA: principal directions."""
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    n = points.shape[0]
    if n < 2:
        raise ValueError("need at least 2 points for PCA")
    mean = points.mean(axis=0)
    xc = points - mean
    cov = (xc.T @ xc) / (n - 1)
    evals, evecs = np.linalg.eigh(cov)
    order = np.argsort(evals)[::-1]
    V = evecs[:, order]
    components = V.T
    return mean, components


def align_ply(ply_path: Path, progress_callback=None, pause_controller=None) -> None:
    """PCA-align the exported splat using splat-transform."""
    ply_path = ply_path.resolve()
    if pause_controller:
        pause_controller.wait_if_paused()
    points = load_ply_point_cloud(ply_path)
    if points.size == 0:
        return
    mean, components = pca_xyz(points)
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
                splat_transform_executable(),
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


def get_frames_sharpness(
    video_capture,
    start_frame,
    end_frame,
    progress_callback=None,
    pause_controller=None,
):
    list_sharpness = []

    current_pos = video_capture.get(cv.CAP_PROP_POS_FRAMES)
    video_capture.set(cv.CAP_PROP_POS_FRAMES, start_frame)

    frame_count = max(0, end_frame - start_frame)
    progress_interval = max(1, frame_count // 100)

    for frame_number in range(start_frame, end_frame):
        if pause_controller:
            pause_controller.wait_if_paused()
        success, frame = video_capture.read()
        if not success:
            break

        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        list_sharpness.append(cv.Laplacian(gray, cv.CV_64F).var())

        processed_count = frame_number - start_frame + 1
        if processed_count % progress_interval == 0 or processed_count == frame_count:
            message = f"Analysing sharpness: {processed_count}/{frame_count} frames"
            print(message)
            emit_progress(progress_callback, message)

    video_capture.set(cv.CAP_PROP_POS_FRAMES, current_pos)

    return np.asarray(list_sharpness, dtype=np.float64)

def main(is_loading, progress_callback=None, pause_controller=None) -> int:
    p = argparse.ArgumentParser(description="Run Opencv + COLMAP + Brush to reconstruct a 3D splat from a video")
    p.add_argument("input_file", help="Absolute path to the input video file")
    p.add_argument("output_file", help="Absolute path for the exported .ply asset")
    p.add_argument("--frame-rate", type=float, default=5.0, help="Frames per second extracted from the video")
    p.add_argument("--start-time", default=None, help="Optional ffmpeg start time, e.g. 00:00:31")
    p.add_argument("--end-time", default=None, help="Optional ffmpeg end time, e.g. 00:06:25")
    p.add_argument("--total-train-iters", type=int, default=10000, help="Brush training iterations")
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU flags for COLMAP if CUDA is available")
    p.add_argument("--keep-temp", action="store_true", help="Keep the temporary COLMAP/Brush working directory")
    p.add_argument("--skip-align", action="store_true", help="Skip PCA alignment with splat-transform")
    args = p.parse_args()
    if not np.isfinite(args.frame_rate) or args.frame_rate <= 0:
        raise ValueError("Frame rate must be greater than zero.")
    if pause_controller:
        pause_controller.wait_if_paused()

    input_path = Path(args.input_file).expanduser()
    output_path = Path(args.output_file).expanduser()
    output_dir = output_path.parent
    output_name = output_path.name
    output_dir.mkdir(parents=True, exist_ok=True)


    emit_progress(
        progress_callback,
        "Checking the video and preparing the output folder.",
    )

    
    try:
        input_path = input_path.resolve()
        output_path = output_path.resolve()
    except OSError as e:
        print(f"run_processing: invalid path: {e}", file=sys.stderr)
        return 1

    if not input_path.is_file():
        print(f"run_processing: input is not a readable file: {input_path}", file=sys.stderr)
        return 1
    if not os.access(input_path, os.R_OK):
        print(f"run_processing: input is not a readable file: {input_path}", file=sys.stderr)
        return 1



    tmp_dir = Path.cwd() / "tmp"
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
    colmap = resolve_colmap()
    brush = resolve_brush(progress_callback)
    if is_loading :
        brush_args = [
            brush,
            sys.argv[1],
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
        )
    else :
        use_colmap_gpu = configure_colmap_gpu(
            colmap,
            args.use_gpu,
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

        snapshot_every = 1

        if args.start_time:
            h, m, sec = map(int, args.start_time.split(":"))
            start_frame = int((h * 3600 + m * 60 + sec) * fps)
            nb_frame = start_frame

        next_snapshot = nb_frame

        if args.end_time:
            h, m, sec = map(int, args.end_time.split(":"))
            end_frame = min(
                end_frame,
                int((h * 3600 + m * 60 + sec) * fps),
            )

        l_sharpness = get_frames_sharpness(
            video_capture,
            nb_frame,
            end_frame,
            progress_callback=progress_callback,
            pause_controller=pause_controller,
        )
        if l_sharpness.size == 0:
            video_capture.release()
            raise RuntimeError("No readable frames were found in the selected video range.")

        end_frame = nb_frame + int(l_sharpness.size)
        score_mean = float(l_sharpness.mean())
        print("score_mean =", score_mean)
        video_capture.set(cv.CAP_PROP_POS_FRAMES, nb_frame)


        sharpness_index = 0
        while nb_frame < end_frame :
            if pause_controller:
                pause_controller.wait_if_paused()
            success, image = video_capture.read()
            if not success:
                break

            if nb_frame >= next_snapshot:
                sharpness = float(l_sharpness[sharpness_index])
                print(f"Frame {nb_frame}: sharpness={sharpness}")

                image_path = images_dir / f"frame_{nb_saved:05d}.jpg"
                if not cv.imwrite(str(image_path), image):
                    video_capture.release()
                    raise RuntimeError(f"Could not write extracted frame: {image_path}")
                nb_saved += 1

                if np.isfinite(score_mean) and score_mean > 0:
                    interval = int(
                        (fps / args.frame_rate) * (sharpness / score_mean)
                    )
                else:
                    interval = int(fps / args.frame_rate)

                interval = min(
                    interval,
                    int(1.5 * fps / args.frame_rate),
                )

                snapshot_every = max(1, interval)
                print("interval =", interval)
                next_snapshot = nb_frame + snapshot_every

            nb_frame += 1
            sharpness_index += 1

        video_capture.release()
        video_duration_seconds = sharpness_index / fps
        print(f"{nb_saved} images extracted")


        # COLMAP feature extraction 

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
            "--FeatureExtraction.num_threads",
            str(num_threads)
        ]
        if use_colmap_gpu:
            feature_args.extend(["--FeatureExtraction.use_gpu", "1"])
        else:
            feature_args.extend(["--FeatureExtraction.use_gpu", "0"])

        run_step(
            "feature_extractor",
            feature_args,
            progress_callback=progress_callback,
            user_message="Searching for recognizable points in each image.",
            done_message="Important points detected in the images.",
            output_callback=indexed_colmap_progress(
                progress_callback,
                "Feature extraction",
                "Processed file",
            ),
            pause_controller=pause_controller,
        )


        #Colmap Matching : 

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

        #Sequential matching arguments
        matcher_args = [
            colmap,
            "sequential_matcher",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--SequentialMatching.overlap",
            str(matching_overlap),
            "--FeatureMatching.max_num_matches", str(max_num_matches),
            "--FeatureMatching.guided_matching", "1",
            "--FeatureMatching.num_threads", str(num_threads),
            
        ]

        #exhaustive_matching arguments
        matcher_args2 = [
            colmap,
            "exhaustive_matcher",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--FeatureMatching.max_num_matches", str(max_num_matches),
            "--FeatureMatching.guided_matching", "1",
            "--FeatureMatching.num_threads", str(num_threads),
        ]


        if use_colmap_gpu:
            matcher_args.extend(["--FeatureMatching.use_gpu", "1"])
        else:
            matcher_args.extend(["--FeatureMatching.use_gpu", "0"])
        
        
        matcher_output = run_step(
            "sequential_matcher",
            matcher_args,
            progress_callback=progress_callback,
            user_message="Comparing images to find camera movement.",
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

        #Colmap Mapping 

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
            "--total-train-iters",
            str(args.total_train_iters),
            "--export-every",
            str(args.total_train_iters),
            "--export-path",
            str(brush_output_dir),
            "--export-name",
            output_name,
            "--with-viewer"
        ]
        brush_output = run_step(
            "brush",
            brush_args,
            progress_callback=progress_callback,
            user_message="Training the 3D model with Brush. This step can take a long time.",
            done_message="Brush has exported the first 3D file.",
            pause_controller=pause_controller,
        )

        ply_path = finalize_brush_output(
            brush_ply_path,
            output_path,
            brush_output,
        )

        try:
            splat_transform = splat_transform_executable()
        except FileNotFoundError:
            splat_transform = None

        #splat_transform using PCA to align the exported splat (optional)

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

        if not args.skip_align and splat_transform:
            align_ply(ply_path, progress_callback, pause_controller)
        elif args.skip_align:
            emit_progress(
                progress_callback,
                "Final alignment is skipped according to the chosen parameters.",
            )

        if not args.keep_temp:
            if pause_controller:
                pause_controller.wait_if_paused()
            emit_progress(progress_callback, "Deleting temporary files.")
            shutil.rmtree(tmp_dir, ignore_errors=True)

        print(f"Done: {ply_path}", flush=True)
        emit_progress(progress_callback, "Processing completed.")
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
    sys.argv = [
        "run_processing.py",
        inputfile,
        outputfile,
        "--frame-rate", str(fps),
        "--total-train-iters", str(totaltrainiters),
    ]
    if starttime:
        sys.argv.extend(["--start-time", str(starttime)])
    if endtime:
        sys.argv.extend(["--end-time", str(endtime)])
    if usegpu:
        sys.argv.append("--use-gpu")
    if keeptemp:
        sys.argv.append("--keep-temp")
    if skipalign:
        sys.argv.append("--skip-align")

    return main(
        False,
        progress_callback=progress_callback,
        pause_controller=pause_controller,
    )

def load(inputfile, progress_callback=None):
    sys.argv = [
        "run_processing.py",
        inputfile,inputfile
    ]
    return main(True, progress_callback=progress_callback)


