#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from plyfile import PlyData
from scipy.spatial.transform import Rotation


def _run_step(label: str, cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n==> {label}", flush=True)
    print("$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _resolve_executable(names: list[str], env_var: str | None = None) -> str:
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(f"Could not find any of {names}")


def _resolve_colmap() -> str:
    return _resolve_executable(["colmap"])


def _resolve_brush() -> str:
    candidates = [
        os.environ.get("BRUSH_BIN"),
        str(Path(__file__).resolve().parent / "brush" / "target" / "debug" / "brush"),
        str(Path("/home/ubuntu/Stage/Test_env/brush/target/debug/brush")),
        shutil.which("brush"),
        shutil.which("brush_app"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return str(Path(candidate).expanduser())
    repo = Path(__file__).resolve().parent / "brush"
    if repo.is_dir():
        print("Building Brush because no binary was found...", flush=True)
        _run_step("build brush", ["cargo", "build", "-p", "brush-app"], cwd=repo)
        built = repo / "target" / "debug" / "brush"
        if built.is_file():
            return str(built)
    raise FileNotFoundError("Brush executable not found")


def _colmap_has_cuda() -> bool:
    try:
        return True
    except subprocess.CalledProcessError:
        return False
    return "without CUDA" not in help_text


def _splat_transform_executable() -> str:
    """Resolve ``splat-transform`` for ``subprocess`` (Windows needs ``.cmd`` path)."""
    override = os.environ.get("SPLAT_TRANSFORM")
    if override:
        return override
    return _resolve_executable(["splat-transform", "splat-transform.cmd", "splat-transform.exe"])


def _load_ply_point_cloud(ply_path: Path) -> np.ndarray:
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


def _pca_xyz(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
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


def _align_ply(ply_path: Path) -> None:
    """PCA-align the exported splat using splat-transform."""
    ply_path = ply_path.resolve()
    points = _load_ply_point_cloud(ply_path)
    if points.size == 0:
        return
    mean, components = _pca_xyz(points)
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
        _run_step(
            "splat-transform (PCA align)",
            [
                _splat_transform_executable(),
                str(ply_path),
                f"--rotate={ex},{ey},{ez}",
                f"--translate={tx},{ty},{tz}",
                str(tmp_path),
                "-w",
            ],
        )
        os.replace(tmp_path, ply_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def main() -> int:
    p = argparse.ArgumentParser(description="Run ffmpeg + COLMAP + Brush to reconstruct a 3D splat from a video")
    p.add_argument("input_file", help="Absolute path to the input video file")
    p.add_argument("output_file", help="Absolute path for the exported .ply asset")
    p.add_argument("--frame-rate", type=float, default=5.0, help="Frames per second extracted from the video")
    p.add_argument("--start-time", default=None, help="Optional ffmpeg start time, e.g. 00:00:31")
    p.add_argument("--end-time", default=None, help="Optional ffmpeg end time, e.g. 00:06:25")
    p.add_argument("--total-train-iters", type=int, default=10000, help="Brush training iterations")
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU flags for COLMAP if CUDA is available")
    p.add_argument("--keep-temp", action="store_true", help="Keep the temporary COLMAP/Brush working directory")
    p.add_argument("--skip-align", action="store_true", help="Skip PCA alignment with splat-transform")
    p.add_argument("--dry-run", action="store_true", help="Only validate the configuration and print commands")
    args = p.parse_args()

    input_path = Path(args.input_file).expanduser()
    output_path = Path(args.output_file).expanduser()

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

    output_dir = output_path.parent
    output_name = output_path.name
    output_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path.cwd() / "tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    images_dir = tmp_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_cmd = ["ffmpeg", "-i", str(input_path)]
    if args.start_time:
        ffmpeg_cmd.extend(["-ss", args.start_time])
    if args.end_time:
        ffmpeg_cmd.extend(["-to", args.end_time])
    ffmpeg_cmd.extend([
        "-vf",
        f"fps={args.frame_rate},scale=iw:ih:flags=lanczos",
        "-c:v",
        "mjpeg",
        "-q:v",
        "2",
        "-y",
        str(images_dir / "frame_%05d.jpg"),
    ])

    colmap = _resolve_colmap()
    brush = _resolve_brush()

    if args.dry_run:
        print("Dry run only. The following steps would be executed:")
        print("  1. ffmpeg")
        print("  2. COLMAP feature extraction")
        print("  3. COLMAP sequential matching")
        print("  4. COLMAP mapper")
        print("  5. Brush training/export")
        print("  6. Optional splat-transform cleanup/alignment")
        return 0

    _run_step("ffmpeg", ffmpeg_cmd)

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
        "--SiftExtraction.max_num_features",
        "16384",
        "--SiftExtraction.num_threads",
        str(os.cpu_count() or 1)
    ]
    if args.use_gpu and _colmap_has_cuda():
        feature_args.extend(["--SiftExtraction.use_gpu", "1"])
    else:
        feature_args.extend(["--SiftExtraction.use_gpu", "0"])
    _run_step("feature_extractor", feature_args)

    matcher_args = [
        colmap,
        "sequential_matcher",
        "--database_path",
        str(tmp_dir / "database.db"),
        "--SequentialMatching.overlap",
        "20",
        "--SiftMatching.max_num_matches", "32768",
        "--SiftMatching.guided_matching", "1",
        "--SiftMatching.num_threads", str(os.cpu_count() or 1),
    ]

    if args.use_gpu and _colmap_has_cuda():
        matcher_args.extend(["--SiftMatching.use_gpu", "1"])
    else:
        matcher_args.extend(["--SiftMatching.use_gpu", "0"])
    _run_step("sequential_matcher", matcher_args)

    sparse_dir = tmp_dir / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

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
        str(os.cpu_count() or 1),
    ]
    _run_step("mapper", mapper_args)

    brush_args = [
        brush,
        str(tmp_dir),
        "--total-train-iters",
        str(args.total_train_iters),
        "--export-every",
        str(args.total_train_iters),
        "--export-path",
        str(output_dir),
        "--export-name",
        output_name,
    ]
    _run_step("brush", brush_args)

    ply_path = output_dir / output_name
    if not ply_path.is_file():
        raise FileNotFoundError(f"Brush did not produce the expected output: {ply_path}")

    try:
        splat_transform = _splat_transform_executable()
    except FileNotFoundError:
        splat_transform = None

    if splat_transform:
        temp_ply = tempfile.NamedTemporaryFile(suffix=".ply", dir=str(output_dir), delete=False)
        temp_ply.close()
        temp_ply_path = Path(temp_ply.name)
        _run_step(
            "splat-transform clean transparents",
            [
                splat_transform,
                str(ply_path),
                "-V",
                "opacity,gt,0.01",
                str(temp_ply_path),
                "-w",
            ],
        )
        os.replace(temp_ply_path, ply_path)

    if not args.skip_align and splat_transform:
        _align_ply(ply_path)

    if not args.keep_temp:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"Done: {ply_path}", flush=True)
    return 0





def test_function(inputfile, outputfile, fps, starttime=None, endtime=None, totaltrainiters=10000, usegpu=True, keeptemp=False, skipalign=False):
    sys.argv = [
        "run_processing.py",
        inputfile,
        outputfile,
        "--frame-rate", str(fps),
        "--start-time", starttime,
        "--end-time", endtime,
        "--total-train-iters", str(totaltrainiters),
    ]
    if usegpu:
        sys.argv.append("--use-gpu")
    if keeptemp:
        sys.argv.append("--keep-temp")
    if skipalign:
        sys.argv.append("--skip-align")

    return main()


input_file = '/home/ubuntu/Stage/DATASETS/chair.mp4'
output_file = '/home/ubuntu/Stage/output/chair.ply'

test_function(input_file,output_file, fps=1.0, totaltrainiters=5000, usegpu=True, keeptemp=False, skipalign=False)