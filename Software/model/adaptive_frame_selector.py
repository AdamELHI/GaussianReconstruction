from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import cv2 as cv
import numpy as np


@dataclass(frozen=True)
class SelectedFrame:
    frame_index: int
    image: np.ndarray
    sharpness: float
    motion_px: float
    reason: str


@dataclass
class _Candidate:
    frame_index: int
    image: np.ndarray
    gray: np.ndarray
    sharpness: float
    motion_px: float


class AdaptiveFrameSelector:
    """Select sharp, spatially distinct video frames for reconstruction.

    Motion values are reported in pixels at the original image resolution even
    though optical flow is computed on a smaller image for performance.
    """

    def __init__(
        self,
        source_fps: float,
        max_output_fps: float | None = None,
        min_motion_px: float = 3.0,
        target_motion_px: float = 45.0,
        max_motion_px: float = 120.0,
        automatic_candidate_motion_ratio: float = 0.05,
        automatic_target_motion_ratio: float = 0.10,
        automatic_max_motion_ratio: float = 0.15,
        automatic_sharpness_percentile: float = 50.0,
        analysis_width: int = 640,
    ) -> None:
        if source_fps <= 0:
            raise ValueError("The source frame rate must be greater than zero.")
        if max_output_fps is not None and max_output_fps <= 0:
            raise ValueError("The output frame rate must be greater than zero.")
        if not 0 <= min_motion_px < target_motion_px < max_motion_px:
            raise ValueError(
                "Motion thresholds must satisfy min < target < max."
            )
        if not (
            0
            < automatic_candidate_motion_ratio
            < automatic_target_motion_ratio
            < automatic_max_motion_ratio
        ):
            raise ValueError(
                "Automatic motion ratios must satisfy candidate < target < max."
            )
        if not 0 <= automatic_sharpness_percentile <= 100:
            raise ValueError("The sharpness percentile must be between 0 and 100.")

        self.frames_per_window = (
            None
            if max_output_fps is None
            else max(1.0, source_fps / max_output_fps)
        )
        self.min_motion_px = float(min_motion_px)
        self.target_motion_px = float(target_motion_px)
        self.max_motion_px = float(max_motion_px)
        self.automatic_candidate_motion_ratio = float(
            automatic_candidate_motion_ratio
        )
        self.automatic_target_motion_ratio = float(
            automatic_target_motion_ratio
        )
        self.automatic_max_motion_ratio = float(automatic_max_motion_ratio)
        self.automatic_sharpness_percentile = float(
            automatic_sharpness_percentile
        )
        self.analysis_width = max(160, int(analysis_width))

        self._selected_index: int | None = None
        self._selected_gray: np.ndarray | None = None
        self._analysis_scale = 1.0
        self._best_candidate: _Candidate | None = None
        self._bridge_candidate: _Candidate | None = None
        self._next_window_frame: float | None = None
        self._sharpness_history = deque(
            maxlen=max(30, round(source_fps * 2)),
        )

    @staticmethod
    def sharpness(gray: np.ndarray) -> float:
        laplacian = cv.Laplacian(gray, cv.CV_32F)
        return float(laplacian.var())

    def _prepare_gray(self, image: np.ndarray) -> np.ndarray:
        gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
        height, width = gray.shape
        self._analysis_scale = min(1.0, self.analysis_width / max(width, 1))
        if self._analysis_scale < 1.0:
            gray = cv.resize(
                gray,
                (round(width * self._analysis_scale), round(height * self._analysis_scale)),
                interpolation=cv.INTER_AREA,
            )
        return gray

    def _motion(self, current_gray: np.ndarray) -> float:
        assert self._selected_gray is not None
        previous = self._selected_gray

        def phase_correlation_motion() -> float:
            shift, response = cv.phaseCorrelate(
                previous.astype(np.float32),
                current_gray.astype(np.float32),
            )
            if not np.isfinite(response) or response < 0.05:
                return 0.0
            return float(
                np.hypot(shift[0], shift[1])
                / max(self._analysis_scale, 1e-6)
            )

        points = cv.goodFeaturesToTrack(
            previous,
            maxCorners=300,
            qualityLevel=0.01,
            minDistance=8,
            blockSize=7,
        )
        if points is None or len(points) < 8:
            return phase_correlation_motion()

        tracked, status, _ = cv.calcOpticalFlowPyrLK(
            previous,
            current_gray,
            points,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(
                cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT,
                30,
                0.01,
            ),
        )
        if tracked is None or status is None:
            return phase_correlation_motion()
        valid = status.reshape(-1).astype(bool)
        if np.count_nonzero(valid) < 8:
            return phase_correlation_motion()

        displacement = tracked[valid] - points[valid]
        distances = np.linalg.norm(displacement.reshape(-1, 2), axis=1)
        # The median ignores independently moving objects and isolated bad flow.
        return float(np.median(distances) / max(self._analysis_scale, 1e-6))

    def _select(self, candidate: _Candidate, reason: str) -> SelectedFrame:
        self._selected_index = candidate.frame_index
        self._selected_gray = candidate.gray
        self._best_candidate = None
        self._bridge_candidate = None
        return SelectedFrame(
            frame_index=candidate.frame_index,
            image=candidate.image,
            sharpness=candidate.sharpness,
            motion_px=candidate.motion_px,
            reason=reason,
        )

    def observe(
        self,
        frame_index: int,
        image: np.ndarray,
    ) -> SelectedFrame | None:
        gray = self._prepare_gray(image)
        sharpness = self.sharpness(gray)
        self._sharpness_history.append(sharpness)

        if self.frames_per_window is None:
            return self._observe_automatic(frame_index, image, gray, sharpness)
        return self._observe_timed(frame_index, image, gray, sharpness)

    def _observe_automatic(
        self,
        frame_index: int,
        image: np.ndarray,
        gray: np.ndarray,
        sharpness: float,
    ) -> SelectedFrame | None:
        if self._selected_index is None:
            return self._select(
                _Candidate(frame_index, image.copy(), gray, sharpness, 0.0),
                "first",
            )

        motion_px = self._motion(gray)
        image_width = image.shape[1]
        candidate_motion_px = max(
            self.target_motion_px * 0.5,
            image_width * self.automatic_candidate_motion_ratio,
        )
        target_motion_px = max(
            self.target_motion_px,
            image_width * self.automatic_target_motion_ratio,
        )
        max_motion_px = max(
            self.max_motion_px,
            image_width * self.automatic_max_motion_ratio,
        )

        sharpness_threshold = float(
            np.percentile(
                self._sharpness_history,
                self.automatic_sharpness_percentile,
            )
        )
        if motion_px < candidate_motion_px:
            return None

        candidate = _Candidate(
            frame_index,
            image.copy(),
            gray,
            sharpness,
            motion_px,
        )
        self._consider_bridge_candidate(candidate)
        if sharpness >= sharpness_threshold:
            self._consider_candidate(candidate)

        if motion_px >= max_motion_px and self._bridge_candidate is not None:
            return self._select(
                self._best_candidate or self._bridge_candidate,
                "bridge",
            )
        if motion_px >= target_motion_px and self._best_candidate is not None:
            return self._select(self._best_candidate, "motion")
        return None

    def _observe_timed(
        self,
        frame_index: int,
        image: np.ndarray,
        gray: np.ndarray,
        sharpness: float,
    ) -> SelectedFrame | None:
        assert self.frames_per_window is not None

        if self._next_window_frame is None:
            self._next_window_frame = frame_index + self.frames_per_window

        selected = None
        if frame_index >= self._next_window_frame:
            selected = self._finish_window()
            while frame_index >= self._next_window_frame:
                self._next_window_frame += self.frames_per_window

        motion_px = 0.0
        if self._selected_gray is not None:
            motion_px = self._motion(gray)
            if motion_px < self.min_motion_px:
                return selected

        candidate = _Candidate(
            frame_index,
            image.copy(),
            gray,
            sharpness,
            motion_px,
        )
        self._consider_candidate(candidate)
        return selected

    def _consider_candidate(self, candidate: _Candidate) -> None:
        if (
            self._best_candidate is None
            or candidate.sharpness > self._best_candidate.sharpness
        ):
            self._best_candidate = candidate

    def _consider_bridge_candidate(self, candidate: _Candidate) -> None:
        if (
            self._bridge_candidate is None
            or candidate.sharpness > self._bridge_candidate.sharpness
        ):
            self._bridge_candidate = candidate

    def _finish_window(self) -> SelectedFrame | None:
        if self._best_candidate is None:
            return None
        reason = "first" if self._selected_index is None else "motion"
        return self._select(self._best_candidate, reason)

    def flush(self) -> SelectedFrame | None:
        """Return the best remaining moved frame at the end of the video."""
        if self.frames_per_window is None:
            if self._best_candidate is None:
                return None
            return self._select(self._best_candidate, "last")

        selected = self._finish_window()
        if selected is None:
            return None
        return SelectedFrame(
            frame_index=selected.frame_index,
            image=selected.image,
            sharpness=selected.sharpness,
            motion_px=selected.motion_px,
            reason="last" if selected.reason != "first" else "first",
        )
