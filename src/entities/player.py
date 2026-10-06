"""The Player entity and its movement rules.

The host's server owns the real Player objects and moves them with
step_movement(). Clients keep copies built from the host's roster and
snapshots, and only draw them.
"""

import math
from dataclasses import dataclass

TEAM_BLUE = "blue"
TEAM_RED = "red"
TEAMS = (TEAM_BLUE, TEAM_RED)


def other_team(team):
    return TEAM_RED if team == TEAM_BLUE else TEAM_BLUE


@dataclass
class Player:
    id: int
    team: str
    character: str | None = None  # None until the player picks a character
    x: float = 0.0  # top-left corner of the hitbox
    y: float = 0.0
    is_host: bool = False

    # Server only: the movement keys this player is holding right now, and the
    # sequence number of the newest input packet (older, late ones are ignored).
    input_x: int = 0
    input_y: int = 0
    last_input_seq: int = 0

    def to_roster_dict(self):
        """The fields sent over TCP in a roster message."""
        return {
            "id": self.id,
            "team": self.team,
            "character": self.character,
            "is_host": self.is_host,
            "x": self.x,
            "y": self.y,
        }

    def apply_roster_dict(self, data):
        """Copy the fields from a roster message into this player.

        Positions are left alone: they come from the much more frequent UDP
        snapshots (see ClientSession._apply_roster for the one exception).
        """
        self.team = data["team"]
        self.character = data["character"]
        self.is_host = data["is_host"]


def step_movement(x, y, input_x, input_y, dt, settings):
    """Return the new (x, y) after moving for dt seconds with the given input."""
    length = math.hypot(input_x, input_y)
    if length > 0.0:
        # Normalize the direction so diagonal movement is not faster.
        distance = settings["player"]["speed"] * dt
        x += input_x / length * distance
        y += input_y / length * distance

    # Keep the hitbox inside the world.
    size = settings["player"]["size"]
    x = max(0.0, min(x, settings["world"]["width"] - size))
    y = max(0.0, min(y, settings["world"]["height"] - size))
    return x, y
