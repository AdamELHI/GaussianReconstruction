import cv2 as cv
import numpy as np

from model.adaptive_frame_selector import AdaptiveFrameSelector


def textured_frame(blur: bool = False, width: int = 160) -> np.ndarray:
    grid = np.indices((120, width)).sum(axis=0)
    gray = ((grid // 4 % 2) * 255).astype(np.uint8)
    if blur:
        gray = cv.GaussianBlur(gray, (15, 15), 0)
    return cv.cvtColor(gray, cv.COLOR_GRAY2BGR)


def test_stationary_frames_are_rejected():
    selector = AdaptiveFrameSelector(30, 10)
    selector._motion = lambda _gray: 1.0

    assert selector.observe(0, textured_frame()) is None
    assert selector.observe(1, textured_frame()) is None
    assert selector.observe(2, textured_frame()) is None
    first = selector.observe(3, textured_frame())
    assert first is not None
    assert first.reason == "first"
    for frame_index in range(4, 30):
        assert selector.observe(frame_index, textured_frame()) is None
    assert selector.flush() is None


def test_automatic_mode_selects_from_motion_without_fps_windows():
    selector = AdaptiveFrameSelector(
        30,
        target_motion_px=30,
        max_motion_px=90,
        automatic_candidate_motion_ratio=0.05,
        automatic_target_motion_ratio=0.10,
        automatic_max_motion_ratio=0.20,
    )
    motion_values = iter((12.0, 20.0, 31.0))

    first = selector.observe(0, textured_frame())
    selector._motion = lambda _gray: next(motion_values)
    assert selector.observe(1, textured_frame(blur=True)) is None
    assert selector.observe(2, textured_frame()) is None
    selected = selector.observe(3, textured_frame(blur=True))

    assert first is not None
    assert first.reason == "first"
    assert selected is not None
    assert selected.frame_index == 2
    assert selected.reason == "motion"


def test_automatic_motion_threshold_scales_with_image_width():
    selector = AdaptiveFrameSelector(30)
    motion_values = iter((70.0, 110.0))
    selector.observe(0, textured_frame(width=1000))
    selector._motion = lambda _gray: next(motion_values)

    assert selector.observe(1, textured_frame(width=1000)) is None
    selected = selector.observe(2, textured_frame(width=1000))

    assert selected is not None
    assert selected.frame_index == 1


def test_automatic_mode_rejects_blurry_motion_frames():
    selector = AdaptiveFrameSelector(30)
    selector.observe(0, textured_frame())
    selector._motion = lambda _gray: 80.0

    assert selector.observe(1, textured_frame(blur=True)) is None
    selected = selector.observe(2, textured_frame())

    assert selected is not None
    assert selected.frame_index == 2


def test_automatic_mode_keeps_a_blurry_bridge_before_flow_breaks():
    selector = AdaptiveFrameSelector(30)
    selector.observe(0, textured_frame())
    selector._motion = lambda _gray: 150.0

    selected = selector.observe(1, textured_frame(blur=True))

    assert selected is not None
    assert selected.frame_index == 1
    assert selected.reason == "bridge"


def test_sharpest_usefully_moved_candidate_is_selected():
    selector = AdaptiveFrameSelector(
        30,
        10,
        min_motion_px=3,
    )
    selector.observe(0, textured_frame(blur=True))
    selector.observe(1, textured_frame())
    selector.observe(2, textured_frame(blur=True))
    first = selector.observe(3, textured_frame(blur=True))
    assert first is not None
    assert first.frame_index == 1

    motion_values = iter((12.0, 18.0, 31.0))
    selector._motion = lambda _gray: next(motion_values)
    assert selector.observe(4, textured_frame(blur=True)) is None
    assert selector.observe(5, textured_frame()) is None
    selected = selector.observe(6, textured_frame(blur=True))

    assert selected is not None
    assert selected.frame_index == 5
    assert selected.reason == "motion"


def test_fps_controls_the_number_of_selected_frames():
    def selected_count(output_fps):
        selector = AdaptiveFrameSelector(30, output_fps)
        selector._motion = lambda _gray: 10.0
        selected = []
        for frame_index in range(30):
            result = selector.observe(frame_index, textured_frame())
            if result is not None:
                selected.append(result)
        result = selector.flush()
        if result is not None:
            selected.append(result)
        return len(selected)

    assert selected_count(5) == 5
    assert selected_count(10) == 10


def test_flush_keeps_the_last_usefully_moved_candidate():
    selector = AdaptiveFrameSelector(30, 10)
    selector.observe(0, textured_frame())
    selector.observe(1, textured_frame())
    selected = selector.flush()

    assert selected is not None
    assert selected.reason == "first"
