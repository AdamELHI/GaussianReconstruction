

from __future__ import annotations
import argparse
import os
import re
import shutil
import cv2 as cv
import subprocess
import sys
import tempfile
from pathlib import Path
import numpy as np
from plyfile import PlyData
from scipy.spatial.transform import Rotation


def emit_progress(progress_callback, message: str) -> None:
    if progress_callback:
        progress_callback(message)


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path | None = None,
    progress_callback=None,
    user_message: str | None = None,
    done_message: str | None = None,
    output_callback=None,
) -> None:
    if user_message:
        emit_progress(progress_callback, user_message)
    print(f"\n==> {label}", flush=True)
    print("$ " + " ".join(cmd), flush=True)
    env = os.environ.copy()

    env.pop("QT_PLUGIN_PATH", None)
    env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)

    if output_callback is None:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, env=env)
    else:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            output_callback(line)
        return_code = process.wait()
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, cmd)
    if done_message:
        emit_progress(progress_callback, done_message)


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


def resolve_executable(names: list[str], env_var: str | None = None) -> str:
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(f"Could not find any of {names}")


def resolve_colmap() -> str:
    return resolve_executable(["colmap"])


def resolve_brush(progress_callback=None) -> str:
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


def align_ply(ply_path: Path, progress_callback=None) -> None:
    """PCA-align the exported splat using splat-transform."""
    ply_path = ply_path.resolve()
    points = load_ply_point_cloud(ply_path)
    if points.size == 0:
        return
    mean, components = pca_xyz(points)
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
        )
        os.replace(tmp_path, ply_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def get_frames_sharpness(
    video_capture, start_frame, end_frame, progress_callback=None
):
    list_sharpness,list_frame = [],[]

    current_pos = video_capture.get(cv.CAP_PROP_POS_FRAMES)

    video_capture.set(cv.CAP_PROP_POS_FRAMES, start_frame)

    for i in range(start_frame, end_frame):
        message = (
            f"Listing sharpness: frame {i}/{int(video_capture.get(cv.CAP_PROP_FRAME_COUNT))}"
        )
        print(message)
        emit_progress(progress_callback, message)
        success, frame = video_capture.read()

        if not success:
            break

        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        sharpness = cv.Laplacian(gray, cv.CV_64F).var()

        list_sharpness.append(sharpness)
        list_frame.append(frame)

    video_capture.set(cv.CAP_PROP_POS_FRAMES, current_pos)

    return np.asarray(list_frame), np.asarray(list_sharpness)

def main(is_loading, progress_callback=None) -> int:
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
        )
    else :     
        print("The next steps in the implementation process are :")
        print("  1. Extracting frames from video (ffmpeg)")
        print("  2. COLMAP feature extraction")
        print("  3. COLMAP sequential matching")
        print("  4. COLMAP mapper")
        print("  5. Brush training/export")
        print("  6. Optional splat-transform cleanup/alignment")
    
        

        video_capture = cv.VideoCapture(str(input_path))

        nb_frame = 0
        nb_saved = 0

        fps = video_capture.get(cv.CAP_PROP_FPS)
        end_frame = int(video_capture.get(cv.CAP_PROP_FRAME_COUNT))

        snapshot_every = 1

        if args.start_time:
            h, m, sec = map(int, args.start_time.split(":"))
            start_frame = int((h * 3600 + m * 60 + sec) * fps)
            nb_frame = start_frame

        next_snapshot = nb_frame

        if args.end_time:
            h, m, sec = map(int, args.end_time.split(":"))
            end_frame = int((h * 3600 + m * 60 + sec) * fps)
        l_frame, l_sharpness = get_frames_sharpness(
            video_capture,
            nb_frame,
            end_frame,
            progress_callback=progress_callback,
        )
        score_mean = l_sharpness.mean()
        print("score_mean =", score_mean)
        video_capture.set(cv.CAP_PROP_POS_FRAMES, nb_frame)


        while nb_frame < end_frame :
            if nb_frame >= next_snapshot:
                sharpness, image = l_sharpness[nb_frame], l_frame[nb_frame]
                print(f"Frame {nb_frame}: sharpness={sharpness}")

                image_path = images_dir / f"frame_{nb_saved:05d}.jpg"
                cv.imwrite(str(image_path), image)
                nb_saved += 1

                interval = min(
                        int((fps / args.frame_rate) * (sharpness / score_mean)),
                        int(1.5 * fps / args.frame_rate)
                    ) 

                snapshot_every = max(1, interval)
                print("interval =", interval)
                next_snapshot = nb_frame + snapshot_every

            nb_frame += 1
                
        print(f"{nb_saved} images extracted")


        # COLMAP feature extraction 

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
            "32768",
            "--SiftExtraction.num_threads",
            str(os.cpu_count() or 1)
        ]
        if args.use_gpu :
            feature_args.extend(["--SiftExtraction.use_gpu", "1"])
        else:
            feature_args.extend(["--SiftExtraction.use_gpu", "0"])

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
        )


        #Colmap Matching : 

        #Sequential matching arguments
        matcher_args = [
            colmap,
            "sequential_matcher",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--SequentialMatching.overlap",
            "50",
            "--SiftMatching.max_num_matches", "32768",
            "--SiftMatching.guided_matching", "1",
            "--SiftMatching.num_threads", str(os.cpu_count() or 1),
            
        ]

        #exhaustive_matching arguments
        matcher_args2 = [
            colmap,
            "exhaustive_matcher",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--SiftMatching.max_num_matches", "32768",
            "--SiftMatching.guided_matching", "1",
            "--SiftMatching.num_threads", str(os.cpu_count() or 1),
        ]


        if args.use_gpu :
            matcher_args.extend(["--SiftMatching.use_gpu", "1"])
        else:
            matcher_args.extend(["--SiftMatching.use_gpu", "0"])
        
        
        run_step(
            "sequential_matcher",
            matcher_args,
            progress_callback=progress_callback,
            user_message="Comparing images to find camera movement.",
            done_message="Images linked together.",
            output_callback=indexed_colmap_progress(
                progress_callback,
                "Matching",
                "Matching image",
            ),
        )

        #Colmap Mapping 

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
        )

        # Brush training (gaussian) and export

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
            "--with-viewer"
        ]
        run_step(
            "brush",
            brush_args,
            progress_callback=progress_callback,
            user_message="Training the 3D model with Brush. This step can take a long time.",
            done_message="Brush has exported the first 3D file.",
        )

        ply_path = output_dir / output_name
        if not ply_path.is_file():
            raise FileNotFoundError(f"Brush did not produce the expected output: {ply_path}")

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
            )
            os.replace(temp_ply_path, ply_path)
        else:
            emit_progress(
                progress_callback,
                "Optional cleaning is ignored; the relevant tool is not available.",
            )

        if not args.skip_align and splat_transform:
            align_ply(ply_path, progress_callback)
        elif args.skip_align:
            emit_progress(
                progress_callback,
                "Final alignment is skipped according to the chosen parameters.",
            )

        if not args.keep_temp:
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

    return main(False, progress_callback=progress_callback)

def load(inputfile):
    sys.argv = [
        "run_processing.py",
        inputfile,inputfile
    ]
    return main(True)


