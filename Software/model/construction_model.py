import math
import re

from pathlib import Path
from typing import Any, Callable

from model.paths import OUTPUT_DIR

DEFAULT_OUTPUT_DIR = OUTPUT_DIR


class ConstructionModel:
    def __init__(self):
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.last_result: dict[str, Any] | None = None

    @staticmethod
    def normalize_input_paths(input_paths) -> list[Path]:
        if isinstance(input_paths, (str, Path)):
            input_paths = [input_paths]
        return [Path(path).expanduser() for path in (input_paths or [])]

    def resolve_output_path(self, input_path, output_path: str | None) -> Path:
        if output_path:
            return Path(output_path).expanduser()
        sources = self.normalize_input_paths(input_path)
        if not sources:
            return DEFAULT_OUTPUT_DIR / "reconstruction.ply"
        source = sources[0]
        return DEFAULT_OUTPUT_DIR / f"{source.stem}.ply"

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

    @staticmethod
    def parse_video_time(value: str | None, field_name: str) -> int | None:
        if value is None:
            return None

        match = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)", value)
        if match is None:
            raise ValueError(
                f"{field_name} must use the HH:MM:SS format "
                "(for example 00:01:30)."
            )

        hours, minutes, seconds = (int(part) for part in match.groups())
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def format_video_time(seconds: float) -> str:
        rounded_seconds = max(0, int(round(seconds)))
        hours, remainder = divmod(rounded_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @staticmethod
    def video_range_for_source(
        source: Path,
        parameters: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        video_ranges = parameters.get("video_ranges") or {}
        source_range = video_ranges.get(str(source), {}) or {}
        return (
            source_range.get("start_time", parameters.get("start_time")),
            source_range.get("end_time", parameters.get("end_time")),
        )

    def validate_reconstruction_parameters(
        self,
        input_path,
        parameters: dict[str, Any],
    ) -> None:
        frame_rate = float(parameters["fps"])
        if not math.isfinite(frame_rate) or frame_rate <= 0:
            raise ValueError("Frames per second must be greater than zero.")

        if int(parameters["total_train_iters"]) <= 0:
            raise ValueError("Brush iterations must be greater than zero.")

        input_paths = self.normalize_input_paths(input_path)
        if not input_paths:
            start_seconds = self.parse_video_time(
                parameters.get("start_time"),
                "Start time",
            )
            end_seconds = self.parse_video_time(
                parameters.get("end_time"),
                "End time",
            )
            if end_seconds is not None and end_seconds <= (start_seconds or 0):
                raise ValueError("End time must be later than start time.")
            return

        parsed_ranges = []
        for source in input_paths:
            start_time, end_time = self.video_range_for_source(
                source,
                parameters,
            )
            start_seconds = self.parse_video_time(
                start_time,
                f"Start time for {source.name}",
            )
            end_seconds = self.parse_video_time(
                end_time,
                f"End time for {source.name}",
            )
            if end_seconds is not None and end_seconds <= (start_seconds or 0):
                raise ValueError(
                    f"End time must be later than start time for {source.name}."
                )
            parsed_ranges.append((source, start_seconds, end_seconds))

        if not any(
            start_seconds is not None or end_seconds is not None
            for _, start_seconds, end_seconds in parsed_ranges
        ):
            return

        import cv2 as cv

        for source, start_seconds, end_seconds in parsed_ranges:
            if start_seconds is None and end_seconds is None:
                continue
            video_capture = cv.VideoCapture(str(source))
            try:
                if not video_capture.isOpened():
                    raise ValueError(
                        f"The selected video could not be opened: {source}"
                    )

                video_fps = video_capture.get(cv.CAP_PROP_FPS)
                frame_count = video_capture.get(cv.CAP_PROP_FRAME_COUNT)
                if (
                    not math.isfinite(video_fps)
                    or video_fps <= 0
                    or not math.isfinite(frame_count)
                    or frame_count <= 0
                ):
                    raise ValueError(
                        "The duration of the selected video could not be "
                        f"determined: {source}"
                    )
                duration_seconds = frame_count / video_fps
            finally:
                video_capture.release()

            formatted_duration = self.format_video_time(duration_seconds)
            if start_seconds is not None and start_seconds >= duration_seconds:
                raise ValueError(
                    f"Start time must be earlier than the duration of "
                    f"{source.name} ({formatted_duration})."
                )
            if end_seconds is not None and end_seconds > duration_seconds:
                raise ValueError(
                    f"End time must not exceed the duration of "
                    f"{source.name} ({formatted_duration})."
                )

    def run_reconstruction(
        self,
        input_path,
        output_path: str | None = None,
        fps: float = 1.0,
        start_time: str | None = None,
        end_time: str | None = None,
        total_train_iters: int = 7000,
        use_gpu: bool = True,
        keep_temp: bool = True,
        skip_align: bool = False,
        colmap_track: bool = False,
        force_exhaustive_matcher: bool = False,
        video_ranges: dict[str, dict[str, str | None]] | None = None,
        progress_callback: Callable[[str], None] | None = None,
        pause_controller: Any | None = None,
    ) -> dict[str, Any]:
        sources = self.normalize_input_paths(input_path)
        if not sources:
            raise FileNotFoundError("No video file was selected.")
        for source in sources:
            if not source.is_file():
                raise FileNotFoundError(f"Video file not found: {source}")

        self.validate_reconstruction_parameters(
            [str(source) for source in sources],
            {
                "fps": fps,
                "start_time": start_time,
                "end_time": end_time,
                "video_ranges": video_ranges or {},
                "total_train_iters": total_train_iters,
            },
        )

        destination = self.resolve_output_path(sources, output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback("Preparing the release file.")

        try:
            import model.run_processing

            exit_code = model.run_processing.run(
                [str(source) for source in sources],
                str(destination),
                fps=fps,
                starttime=start_time,
                endtime=end_time,
                totaltrainiters=total_train_iters,
                usegpu=use_gpu,
                keeptemp=keep_temp,
                skipalign=skip_align,
                colmaptrack=colmap_track,
                forceexhaustivematcher=force_exhaustive_matcher,
                videoranges=video_ranges or {},
                progress_callback=progress_callback,
                pause_controller=pause_controller,
            )
        except model.run_processing.ReconstructionCancelled:
            raise
        except (FileNotFoundError, ModuleNotFoundError, ImportError) as exc:
            if progress_callback:
                progress_callback(
                    "A necessary tool is missing. Creating a backup file."
                )
                progress_callback(f"Error details: {exc}")
            self.write_placeholder_ply(destination, str(exc))
            result = {
                "success": False,
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
                    "An error has interrupted the calculation. A backup file is being created."
                )
                progress_callback(f"Error details: {exc}")
            self.write_placeholder_ply(destination, str(exc))
            result = {
                "success": False,
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
                    progress_callback("Final 3D File has been created.")
                result = {
                    "success": True,
                    "placeholder": False,
                    "path": str(destination),
                    "message": "Reconstruction completed successfully.",
                }
            else:
                if progress_callback:
                    progress_callback(
                        "The calculation finished without producing a usable 3D file. Creating a backup file."
                    )
                self.write_placeholder_ply(
                    destination,
                    "The reconstruction script did not produce a PLY file.",
                )
                result = {
                    "success": False,
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
