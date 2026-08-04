import struct

from model.run_processing import (
    colmap_matcher_name,
    colmap_registered_image_names,
    colmap_registered_image_count,
    colmap_sparse_model_stats,
    create_reconstruction_work_dir,
    exhaustive_geometry_args,
    exhaustive_matching_progress,
    inter_video_geometry_args,
    imported_matching_progress,
    mapping_progress,
    select_video_anchor_names,
    sequential_matching_overlap,
    video_frames_dir,
    write_inter_video_anchor_match_list,
    write_intra_video_match_list,
)


def test_single_video_uses_sequential_matching_by_default():
    assert colmap_matcher_name(1) == "sequential_matcher"


def test_multiple_videos_use_imported_anchor_pairs():
    assert colmap_matcher_name(2) == "matches_importer"


def test_exhaustive_matching_can_be_forced_for_one_video():
    assert colmap_matcher_name(1, True) == "exhaustive_matcher"


def test_exhaustive_matching_uses_stricter_geometric_verification():
    assert exhaustive_geometry_args() == [
        "--TwoViewGeometry.min_num_inliers",
        "60",
        "--TwoViewGeometry.min_inlier_ratio",
        "0.30",
        "--TwoViewGeometry.max_error",
        "2.0",
    ]


def test_inter_video_matching_uses_strict_geometric_verification():
    assert inter_video_geometry_args() == [
        "--TwoViewGeometry.min_num_inliers",
        "100",
        "--TwoViewGeometry.min_inlier_ratio",
        "0.45",
        "--TwoViewGeometry.max_error",
        "1.5",
    ]


def test_reconstructions_use_distinct_working_directories(tmp_path):
    first = create_reconstruction_work_dir(tmp_path)
    second = create_reconstruction_work_dir(tmp_path)

    assert first != second
    assert first.parent == tmp_path
    assert second.parent == tmp_path
    assert first.is_dir()
    assert second.is_dir()


def test_each_video_uses_a_separate_frame_directory(tmp_path):
    assert video_frames_dir(tmp_path, 1) == tmp_path / "video_001"
    assert video_frames_dir(tmp_path, 2) == tmp_path / "video_002"


def test_intra_video_pair_list_never_crosses_video_directories(tmp_path):
    images_dir = tmp_path / "images"
    for video_name in ("video_001", "video_002"):
        video_dir = images_dir / video_name
        video_dir.mkdir(parents=True)
        for frame_index in range(4):
            (video_dir / f"frame_{frame_index:06d}.jpg").touch()

    match_list = tmp_path / "pairs.txt"
    num_pairs = write_intra_video_match_list(images_dir, match_list, overlap=2)
    pairs = [line.split() for line in match_list.read_text().splitlines()]

    assert num_pairs == 10
    assert all(first.split("/")[0] == second.split("/")[0] for first, second in pairs)


def test_anchor_selection_prefers_sharp_non_bridge_frames():
    records = [
        ("video_001/frame_000.jpg", 10.0, "bridge"),
        ("video_001/frame_001.jpg", 20.0, "motion"),
        ("video_001/frame_002.jpg", 30.0, "motion"),
        ("video_001/frame_003.jpg", 40.0, "motion"),
    ]
    assert select_video_anchor_names(records, max_anchors=2) == [
        "video_001/frame_001.jpg",
        "video_001/frame_003.jpg",
    ]


def test_inter_video_anchor_list_contains_only_cross_video_pairs(tmp_path):
    video_records = [
        [
            ("video_001/frame_001.jpg", 20.0, "motion"),
            ("video_001/frame_002.jpg", 30.0, "motion"),
        ],
        [
            ("video_002/frame_001.jpg", 25.0, "motion"),
            ("video_002/frame_002.jpg", 35.0, "motion"),
        ],
        [("video_003/frame_001.jpg", 40.0, "motion")],
    ]
    match_list = tmp_path / "inter_pairs.txt"

    num_pairs, num_anchors = write_inter_video_anchor_match_list(
        video_records,
        match_list,
    )
    pairs = [line.split() for line in match_list.read_text().splitlines()]

    assert num_anchors == 5
    assert num_pairs == 8
    assert all(first.split("/")[0] != second.split("/")[0] for first, second in pairs)


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


def test_imported_matching_progress_reports_pair_blocks():
    messages = []
    reporter = imported_matching_progress(messages.append, "Cross-video matching")

    reporter("Processing block [1/12]")
    reporter("Processing block [1/12]")
    reporter("Processing block [12/12]")

    assert messages == [
        "Cross-video matching: 1/12 pair blocks processed.",
        "Cross-video matching: 12/12 pair blocks processed.",
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


def write_colmap_images_bin(path, names):
    with path.open("wb") as model_file:
        model_file.write(struct.pack("<Q", len(names)))
        for image_id, name in enumerate(names, start=1):
            model_file.write(
                struct.pack(
                    "<I7dI",
                    image_id,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1,
                )
            )
            model_file.write(name.encode("utf-8") + b"\0")
            model_file.write(struct.pack("<Q", 0))


def test_sparse_model_stats_report_registered_images_per_video(tmp_path):
    sparse_dir = tmp_path / "sparse"
    first_model = sparse_dir / "0"
    second_model = sparse_dir / "1"
    first_model.mkdir(parents=True)
    second_model.mkdir()
    write_colmap_images_bin(
        first_model / "images.bin",
        [
            "video_001/frame_001.jpg",
            "video_001/frame_002.jpg",
            "video_002/frame_001.jpg",
        ],
    )
    write_colmap_images_bin(
        second_model / "images.bin",
        ["video_003/frame_001.jpg"],
    )

    assert colmap_registered_image_names(first_model) == [
        "video_001/frame_001.jpg",
        "video_001/frame_002.jpg",
        "video_002/frame_001.jpg",
    ]
    assert colmap_sparse_model_stats(sparse_dir) == [
        {
            "model": "0",
            "registered": 3,
            "videos": {"video_001": 2, "video_002": 1},
        },
        {
            "model": "1",
            "registered": 1,
            "videos": {"video_003": 1},
        },
    ]
