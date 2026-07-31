from model.run_processing import (
    colmap_matcher_name,
    colmap_registered_image_count,
    create_reconstruction_work_dir,
    exhaustive_geometry_args,
    exhaustive_matching_progress,
    mapping_progress,
    sequential_matching_overlap,
)


def test_single_video_uses_sequential_matching_by_default():
    assert colmap_matcher_name(1) == "sequential_matcher"


def test_multiple_videos_use_exhaustive_matching():
    assert colmap_matcher_name(2) == "exhaustive_matcher"


def test_exhaustive_matching_can_be_forced_for_one_video():
    assert colmap_matcher_name(1, True) == "exhaustive_matcher"


def test_exhaustive_matching_uses_stricter_geometric_verification():
    assert exhaustive_geometry_args() == [
        "--TwoViewGeometry.min_num_inliers",
        "50",
        "--TwoViewGeometry.min_inlier_ratio",
        "0.30",
        "--TwoViewGeometry.max_error",
        "2.0",
    ]


def test_reconstructions_use_distinct_working_directories(tmp_path):
    first = create_reconstruction_work_dir(tmp_path)
    second = create_reconstruction_work_dir(tmp_path)

    assert first != second
    assert first.parent == tmp_path
    assert second.parent == tmp_path
    assert first.is_dir()
    assert second.is_dir()


def test_sequential_overlap_is_bounded_by_available_frames():
    assert sequential_matching_overlap(12, 6.0) == 10


def test_exhaustive_matching_progress_reports_linear_block_progress():
    messages = []
    reporter = exhaustive_matching_progress(messages.append)

    reporter("Processing block [1/3, 1/3]")
    reporter("Processing block [1/3, 2/3]")
    reporter("Processing block [3/3, 3/3]")

    assert messages == [
        "Matching: 1/9 blocks processed.",
        "Matching: 2/9 blocks processed.",
        "Matching: 9/9 blocks processed.",
    ]


def test_mapping_progress_ignores_repeated_registration_and_finishes():
    messages = []
    reporter = mapping_progress(messages.append, 435)

    reporter("Registering image #12")
    reporter("Registering image #12")
    reporter("Registering image #13")
    reporter.finish(424)

    assert messages == [
        "Mapping: 1/435 frames dealt with.",
        "Mapping: 2/435 frames dealt with.",
        "Mapping: 435/435 frames dealt with (424 registered, 11 skipped).",
    ]


def test_colmap_registered_image_count_reads_binary_header(tmp_path):
    model_dir = tmp_path / "0"
    model_dir.mkdir()
    (model_dir / "images.bin").write_bytes((424).to_bytes(8, "little"))

    assert colmap_registered_image_count(model_dir) == 424


def test_colmap_registered_image_count_handles_missing_model(tmp_path):
    assert colmap_registered_image_count(tmp_path / "missing") is None
