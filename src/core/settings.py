"""Loads the JSON data files in data/.

Both the server and the client call these once at startup, so tuning values
can be changed by editing the files instead of the code.
"""

import json
from pathlib import Path

# src/core/settings.py -> parents[2] is the repository root.
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_json(file_name):
    """Read one JSON file from the data folder."""
    with open(DATA_DIR / file_name, encoding="utf-8") as file:
        return json.load(file)


def load_settings():
    """Network, world, player and spawn tuning values."""
    return load_json("settings.json")


def load_characters():
    """The list of selectable characters (id, display name, shape)."""
    return load_json("characters.json")["characters"]
