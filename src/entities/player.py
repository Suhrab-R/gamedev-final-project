"""The Player entity and its movement rules.

This file is used by both sides:
- the server owns the real Player objects and moves them with step_movement();
- the client keeps copies built from the server's roster, and runs the same
  step_movement() to predict its own player (see net/client_sync.py).
"""

import math
from dataclasses import dataclass, field

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

    # Server only: movement commands received from this player's client that
    # haven't been applied yet, and the sequence number of the last applied one.
    pending_commands: list = field(default_factory=list)
    last_command_seq: int = 0

    # Client only: where this player is drawn this frame (None = not drawn yet).
    draw_x: float | None = None
    draw_y: float | None = None

    def to_roster_dict(self):
        """The fields sent over TCP in a roster message (positions go over UDP)."""
        return {
            "id": self.id,
            "team": self.team,
            "character": self.character,
            "is_host": self.is_host,
        }

    def apply_roster_dict(self, data):
        """Copy the fields from a roster message into this player."""
        self.team = data["team"]
        self.character = data["character"]
        self.is_host = data["is_host"]


def step_movement(x, y, input_x, input_y, dt, settings):
    """Return the new (x, y) after moving for dt seconds with the given input.

    The server and the client both call this with the same inputs, so the
    client's prediction of its own player matches what the server computes.
    """
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
