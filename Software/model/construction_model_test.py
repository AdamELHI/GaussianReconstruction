import os
from model.construction_model import ConstructionModel
from pathlib import Path


def test_write_placeholder_ply():

    if os.path.exists("./ply_test/dummy.ply"):
        os.remove("./ply_test/dummy.ply")

    model = ConstructionModel()
    model.write_placeholder_ply(Path("./ply_test/dummy.ply"), "test")

    assert os.path.exists("./ply_test/dummy.ply")

    os.remove("./ply_test/dummy.ply")


def test_resolve_output_path_uses_first_selected_video():
    model = ConstructionModel()

    output_path = model.resolve_output_path(
        ["/videos/first.mp4", "/videos/second.mp4"],
        None,
    )

    assert output_path.name == "first.ply"


def test_normalize_input_paths_preserves_all_selected_videos():
    paths = ConstructionModel.normalize_input_paths(
        ["~/first.mp4", "~/second.mp4"]
    )

    assert [path.name for path in paths] == ["first.mp4", "second.mp4"]


def test_video_range_is_selected_for_each_source():
    parameters = {
        "start_time": None,
        "end_time": None,
        "video_ranges": {
            "/videos/first.mp4": {
                "start_time": "00:00:05",
                "end_time": "00:00:20",
            },
            "/videos/second.mp4": {
                "start_time": "00:01:00",
                "end_time": None,
            },
        },
    }

    assert ConstructionModel.video_range_for_source(
        Path("/videos/first.mp4"),
        parameters,
    ) == ("00:00:05", "00:00:20")
    assert ConstructionModel.video_range_for_source(
        Path("/videos/second.mp4"),
        parameters,
    ) == ("00:01:00", None)
