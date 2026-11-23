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


def hitbox_size(settings):
    """(width, height) of every player's hitbox, in screen pixels.

    settings.json gives the hitbox in sprite pixels (the same units as the
    sprite images) and one "scale": how many screen pixels each sprite pixel
    becomes. Multiplying both by the same scale means changing that one
    number resizes the sprites and the hitbox together.
    """
    player = settings["player"]
    return player["hitbox_width"] * player["scale"], player["hitbox_height"] * player["scale"]


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
    # Lives left (settings.json "player.lives" to start). At 0 the player is
    # out: no longer in the level. Sent in snapshots for the HUD.
    lives: int = 0

    # Server only: the keys this player is holding right now, and the sequence
    # number of the newest input packet (older, late ones are ignored).
    input_x: int = 0  # -1 left (A), 0, 1 right (D)
    input_y: int = 0  # -1 up (W), 0, 1 down (S); not used by the physics yet
    jump_held: bool = False  # space
    run_held: bool = False  # shift
    last_input_seq: int = 0

    # Physics state (see entities/physics.py). The host's server owns it;
    # vx and on_ground are also sent to clients in snapshots, because the
    # walk animation needs them (see entities/animation.py).
    vx: float = 0.0  # pixels per second; positive is right
    on_ground: bool = False
    # Just respawned: obstacles and enemies can't hurt them, and they blink.
    # Also sent in snapshots, so every screen can make them blink.
    invulnerable: bool = False
    # Server only from here down.
    vy: float = 0.0  # pixels per second; positive is down
    jump_rising: bool = False  # rising from a jump with jump still held (weak gravity)
    jump_was_held: bool = False  # jump_held last frame, to detect a fresh press
    jump_buffer_left: float = 0.0  # seconds a recent jump press stays usable (jump buffering)
    standing_on: int | None = None  # index of the platform the player is standing on, if any
    air_speed_cap: float = 0.0  # top speed while in the air, fixed at the moment of leaving the ground
    # The last platform the player stood on (None = the ground) and where on
    # it, so falling below the team's camera can put them back there.
    last_platform: int | None = None
    last_platform_x: float = 0.0
    # How fast (px/s, + = right) the thing the player is standing on is moving:
    # a runner level's obstacles move left, everything else is still (0). In
    # the air it keeps the value from what they jumped or walked off.
    ground_vx: float = 0.0
    flying: bool = False  # the level editor's fly mode (moves freely, no gravity or collisions)
    invulnerable_left: float = 0.0  # seconds of respawn protection left (see GameServer)

    # Drawing only, kept by each screen for itself (never sent): how far this
    # player has walked since they last stood still, which picks the walk frame.
    walk_distance: float = 0.0

    @property
    def in_play(self):
        """True while this player is in the level: has picked a character and
        still has lives left."""
        return self.character is not None and self.lives > 0

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

