from dataclasses import dataclass

import numpy as np
import pandas as pd # type: ignore


LABEL_COLUMN_NAMES = {
    "label",
    "labels",
    "class",
    "classe",
    "category",
    "categorie",
}


@dataclass
class DatasetInfo:
    has_header: bool
    column_names: list[str]
    feature_names: list[str]
    feature_indices: list[int]
    label_index: int | None
    label_name: str | None
    label_mapping: dict | None








def load_file_dataset(path):

    pass 

def validate_file(file):
    """
    Verifie que le fichier est au bon format.
    """
    pass 



def load_and_validate_file(path):
    load_file_dataset(path)
    validate_file(path)

