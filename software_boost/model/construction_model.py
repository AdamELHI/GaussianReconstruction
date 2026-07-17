import sys

from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ConstructionModel:
    def __init__(self):
        self.last_result: dict[str, Any] | None = None

    def resolve_output_path(self, input_path: str, output_path: str | None) -> Path:
        if output_path:
            return Path(output_path).expanduser()
        source = Path(input_path).expanduser()
        return source.with_suffix(".ply")

    def write_placeholder_ply(self, output_path: Path, reason: str) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            "ply\n"
            "format ascii 1.0\n"
            "element vertex 1\n"
            "property float x\n"
            "property float y\n"
            "property float z\n"
            "end_header\n"
            "0.0 0.0 0.0\n",
            encoding="utf-8",
        )

    def run_reconstruction(
        self,
        input_path: str,
        output_path: str | None = None,
        fps: float = 1.0,
        start_time: str | None = None,
        end_time: str | None = None,
        total_train_iters: int = 7000,
        use_gpu: bool = True,
        keep_temp: bool = True,
        skip_align: bool = False,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        source = Path(input_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Video file not found: {source}")

        destination = self.resolve_output_path(str(source), output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback("Préparation du dossier de sortie.")

        try:
            import model.run_processing

            exit_code = model.run_processing.run(
                str(source),
                str(destination),
                fps=fps,
                starttime=start_time,
                endtime=end_time,
                totaltrainiters=total_train_iters,
                usegpu=use_gpu,
                keeptemp=keep_temp,
                skipalign=skip_align,
                progress_callback=progress_callback,
            )
        except (FileNotFoundError, ModuleNotFoundError, ImportError) as exc:
            if progress_callback:
                progress_callback(
                    "Un outil nécessaire manque. Création d'un fichier de secours."
                )
            self.write_placeholder_ply(destination, str(exc))
            result = {
                "success": True,
                "placeholder": True,
                "path": str(destination),
                "message": (
                    "The reconstruction pipeline could not run because the external Brush tool or its Python dependencies are missing. "
                    f"A placeholder PLY file was created instead: {exc}"
                ),
            }
        except Exception as exc:
            if progress_callback:
                progress_callback(
                    "Une erreur a interrompu le calcul. Création d'un fichier de secours."
                )
            self.write_placeholder_ply(destination, str(exc))
            result = {
                "success": True,
                "placeholder": True,
                "path": str(destination),
                "message": (
                    "The reconstruction could not finish, so a placeholder PLY file was created. "
                    f"Details: {exc}"
                ),
            }
        else:
            if exit_code == 0 and destination.exists():
                if progress_callback:
                    progress_callback("Le fichier 3D final a été créé.")
                result = {
                    "success": True,
                    "placeholder": False,
                    "path": str(destination),
                    "message": "Reconstruction completed successfully.",
                }
            else:
                if progress_callback:
                    progress_callback(
                        "Le calcul s'est terminé sans fichier 3D utilisable. Creation d'un fichier de secours."
                    )
                self.write_placeholder_ply(
                    destination,
                    "The reconstruction script did not produce a PLY file.",
                )
                result = {
                    "success": True,
                    "placeholder": True,
                    "path": str(destination),
                    "message": (
                        "The reconstruction script did not produce a PLY file, so a placeholder file "
                        "was created instead."
                    ),
                }

        self.last_result = result
        return result

    def load_reconstruction(self, file_path: str) -> dict[str, Any]:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Reconstruction file not found: {path}")
        else :

            return {
                "success": True,
                "placeholder": not path.suffix.lower() == ".ply",
                "path": str(path),
                "message": f"Loaded reconstruction file: {path.name}",
            }
