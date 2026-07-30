from model.run_processing import (
    colmap_registered_image_count,
    mapping_progress,
)


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
