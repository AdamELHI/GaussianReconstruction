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
