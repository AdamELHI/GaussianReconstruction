import gzip
import os
import pickle
from pathlib import Path


CONSTRUCT_FILE_FORMAT = "PlayTest CONSTRUCT session"
CONSTRUCT_FILE_VERSION = 1


def save_construction_file(path, session_state):
    """Enregistre une session  compressée avec pickle."""
    destination = Path(path)
    temporary_path = Path(f"{destination}.tmp")
    document = {
        "format": CONSTRUCT_FILE_FORMAT,
        "version": CONSTRUCT_FILE_VERSION,
        "session": session_state,
    }

    try:
        with gzip.open(temporary_path, "wb") as file:
            pickle.dump(document, file, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporary_path, destination)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def load_construction_file(path):
    """Charge une session CONSTRUCT créée par save_construction_file."""
    with gzip.open(path, "rb") as file:
        document = pickle.load(file)

    if not isinstance(document, dict):
        raise ValueError("Le fichier ne contient pas un dictionnaire valide")
    if document.get("format") != CONSTRUCT_FILE_FORMAT:
        raise ValueError("Ce fichier n'est pas une session ")
    if document.get("version") != CONSTRUCT_FILE_VERSION:
        raise ValueError("Cette version du fichier  n'est pas supportée")

    session = document.get("session")
    if not isinstance(session, dict):
        raise ValueError("La session est invalide")
    return session
