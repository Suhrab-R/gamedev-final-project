"""Loads the JSON data files in data/.

Both the server and the client call these once at startup, so tuning values
can be changed by editing the files instead of the code. settings.json can
also be re-read while the game runs (F5, see reload_settings).
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


def reload_settings(settings):
    """Re-read settings.json into the existing settings dict.

    The new values are copied into the same dict object (not a new one),
    so the game, the server and the physics, which all hold this dict, see
    them straight away without being told.

    Returns None on success, or an error message if the file couldn't be
    used; then the old values are kept so a typo can't crash the game.
    """
    try:
        new_settings = load_settings()
    except (OSError, json.JSONDecodeError) as error:
        return f"settings.json not reloaded: {error}"

    # Every value the game uses must still be there, or the next frame
    # would crash looking for it.
    for section, values in settings.items():
        for key in values:
            if key not in new_settings.get(section, {}):
                return f"settings.json not reloaded: missing \"{section}\" -> \"{key}\""

    for section, values in new_settings.items():
        settings.setdefault(section, {}).update(values)
    return None


def load_characters():
    """The list of selectable characters (id, display name, per-team sprites if any)."""
    return load_json("characters.json")["characters"]
