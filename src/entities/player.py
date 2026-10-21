"""The Player entity.

The host's server owns the real Player objects and moves them with
entities.physics.step_player(). Clients keep copies built from the host's
roster and snapshots, and only draw them.
"""

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
    facing: int = 1  # 1 = facing right, -1 = facing left (flips the sprite)
    # Goes up by 1 every time this player jumps (wrapping 255 -> 0). Sent in
    # snapshots; a screen plays the jump sound when it sees the number change.
    jump_count: int = 0

    # Server only: the keys this player is holding right now, and the sequence
    # number of the newest input packet (older, late ones are ignored).
    input_x: int = 0  # -1 left (A), 0, 1 right (D)
    input_y: int = 0  # -1 up (W), 0, 1 down (S); not used by the physics yet
    jump_held: bool = False  # space
    run_held: bool = False  # shift
    last_input_seq: int = 0

    # Server only: physics state (see entities/physics.py).
    vx: float = 0.0  # pixels per second; positive is right
    vy: float = 0.0  # pixels per second; positive is down
    on_ground: bool = False
    jump_rising: bool = False  # rising from a jump with jump still held (weak gravity)
    jump_was_held: bool = False  # jump_held last frame, to detect a fresh press
    jump_buffer_left: float = 0.0  # seconds a recent jump press stays usable (jump buffering)

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

