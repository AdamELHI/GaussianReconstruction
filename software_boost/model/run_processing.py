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
) -> None:
    if user_message:
        emit_progress(progress_callback, user_message)
    print(f"\n==> {label}", flush=True)
    print("$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)
    if done_message:
        emit_progress(progress_callback, done_message)


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
    repo = Path(__file__).resolve().parent / "brush"
    if repo.is_dir():
        print("Building Brush because no binary was found...", flush=True)
        run_step(
            "build brush",
            ["cargo", "build", "-p", "brush-app"],
            cwd=repo,
            progress_callback=progress_callback,
            user_message="Compilation de Brush, car aucun executable pret n'a ete trouve.",
            done_message="Brush est compile et pret a etre utilise.",
        )
        built = repo / "target" / "debug" / "brush"
        if built.is_file():
            return str(built)
    raise FileNotFoundError("Brush executable not found")


def colmap_has_cuda() -> bool:
    try:
        return True
    except subprocess.CalledProcessError:
        return False
    return "without CUDA" not in help_text


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
            user_message="Recentrage du modele 3D pour faciliter son affichage.",
            done_message="Modele 3D recentre.",
        )
        os.replace(tmp_path, ply_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def main(is_loading, progress_callback=None) -> int:
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
    output_dir = output_path.parent
    output_name = output_path.name
    output_dir.mkdir(parents=True, exist_ok=True)

    emit_progress(
        progress_callback,
        "Verification de la video et preparation du dossier de sortie.",
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
        "Preparation du dossier temporaire pour les images de travail.",
    )

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

    emit_progress(
        progress_callback,
        "Verification des outils necessaires a la reconstruction.",
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
            user_message="Ouverture du fichier 3D dans le visualiseur.",
            done_message="Visualisation terminee.",
        )
    else :     
        


        if args.dry_run:
            print("Dry run only. The following steps would be executed:")
            print("  1. ffmpeg")
            print("  2. COLMAP feature extraction")
            print("  3. COLMAP sequential matching")
            print("  4. COLMAP mapper")
            print("  5. Brush training/export")
            print("  6. Optional splat-transform cleanup/alignment")
            return 0

        run_step(
            "ffmpeg",
            ffmpeg_cmd,
            progress_callback=progress_callback,
            user_message="Extraction d'images depuis la video.",
            done_message="Images extraites depuis la video.",
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
            "--SiftExtraction.max_num_features",
            "16384",
            "--SiftExtraction.num_threads",
            str(os.cpu_count() or 1)
        ]
        if args.use_gpu and colmap_has_cuda():
            feature_args.extend(["--SiftExtraction.use_gpu", "1"])
        else:
            feature_args.extend(["--SiftExtraction.use_gpu", "0"])
        run_step(
            "feature_extractor",
            feature_args,
            progress_callback=progress_callback,
            user_message="Recherche des points reconnaissables dans chaque image.",
            done_message="Points importants detectes dans les images.",
        )

        matcher_args = [
            colmap,
            "sequential_matcher",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--SequentialMatching.overlap",
            "10",
            "--SiftMatching.max_num_matches", "32768",
            "--SiftMatching.guided_matching", "1",
            "--SiftMatching.num_threads", str(os.cpu_count() or 1),
        ]

        if args.use_gpu and colmap_has_cuda():
            matcher_args.extend(["--SiftMatching.use_gpu", "1"])
        else:
            matcher_args.extend(["--SiftMatching.use_gpu", "0"])
        run_step(
            "sequential_matcher",
            matcher_args,
            progress_callback=progress_callback,
            user_message="Comparaison des images entre elles pour retrouver le mouvement de la camera.",
            done_message="Images reliees entre elles.",
        )

        sparse_dir = tmp_dir / "sparse"
        sparse_dir.mkdir(parents=True, exist_ok=True)

        mapper_args = [
            colmap,
            "mapper",
            "GLOBAL",
            "--database_path",
            str(tmp_dir / "database.db"),
            "--image_path",
            str(images_dir),
            "--output_path",
            str(sparse_dir),
            "--Mapper.num_threads",
            str(os.cpu_count() or 1),
        ]
        run_step(
            "mapper",
            mapper_args,
            progress_callback=progress_callback,
            user_message="Construction d'une premiere structure 3D a partir des images.",
            done_message="Structure 3D de base construite.",
        )

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
            user_message="Entrainement du modele 3D avec Brush. Cette etape peut durer longtemps.",
            done_message="Brush a exporte un premier fichier 3D.",
        )

        ply_path = output_dir / output_name
        if not ply_path.is_file():
            raise FileNotFoundError(f"Brush did not produce the expected output: {ply_path}")

        try:
            splat_transform = splat_transform_executable()
        except FileNotFoundError:
            splat_transform = None

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
                user_message="Nettoyage des points presque invisibles dans le fichier 3D.",
                done_message="Fichier 3D nettoye.",
            )
            os.replace(temp_ply_path, ply_path)
        else:
            emit_progress(
                progress_callback,
                "Nettoyage optionnel ignore, l'outil correspondant n'est pas disponible.",
            )

        if not args.skip_align and splat_transform:
            align_ply(ply_path, progress_callback)
        elif args.skip_align:
            emit_progress(
                progress_callback,
                "Alignement final ignore selon les parametres choisis.",
            )

        if not args.keep_temp:
            emit_progress(progress_callback, "Suppression des fichiers temporaires.")
            shutil.rmtree(tmp_dir, ignore_errors=True)

        print(f"Done: {ply_path}", flush=True)
        emit_progress(progress_callback, "Traitement termine.")
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


input_file = '/home/ubuntu/Stage/DATASETS/meetingroom.mp4'
output_file = '/home/ubuntu/Stage/output/meetingroom.ply'

#run(input_file,output_file, fps=1.0, totaltrainiters=1000, usegpu=True, keeptemp=False, skipalign=False)
