import gzip
import os
import pickle
from pathlib import Path


CONSTRUCT_FILE_FORMAT = "PlayTest CONSTRUCT session"
CONSTRUCT_FILE_VERSION = 1


def save_construction_file(path, session_state):
    """Saves a session compressed using pickle."""
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
    """Loads a CONSTRUCT session created by save_construction_file."""
    with gzip.open(path, "rb") as file:
        document = pickle.load(file)
    
    if not isinstance(document, dict):
        raise ValueError("The file does not contain a valid dictionary")
    if document.get("format") != CONSTRUCT_FILE_FORMAT:
        raise ValueError("The file is not a CONSTRUCT session")
    if document.get("version") != CONSTRUCT_FILE_VERSION:
        raise ValueError("This version of the file  is not supported")

    session = document.get("session")
    if not isinstance(session, dict):
        raise ValueError("The session is invalid")
    return session
