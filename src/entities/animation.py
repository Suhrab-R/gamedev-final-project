"""Chooses which sprite frame to draw for a player.

The walk cycle is driven by distance, not time: the frame changes every
`walk_frame_distance` pixels walked (settings.json -> animation). So a
running player, who covers ground twice as fast, automatically animates
twice as fast, and a player sliding to a stop slows their legs down with
them, without a separate run animation.

Every screen does this for itself from the speed and on-ground flag in
the host's snapshots, so nothing about animation is sent over the network.
"""

# The frames of one walk cycle, in order, the same 3-frame loop Super Mario
# World uses: full stride, mid step, feet together. It starts on walk_1 so
# the legs move as soon as you start walking. A character without these
# images just shows idle (see Assets.character_texture).
WALK_CYCLE = ("walk_1", "walk_2", "walk_3")

# Shown the whole time a player is in the air (like SMW's jump pose).
JUMP_FRAME = "jump"


def is_walking(player):
    """On the ground and moving sideways (pushing into a wall counts as standing)."""
    return player.on_ground and player.vx != 0


def advance(player, dt):
    """Add the distance walked this frame; call once per player per frame."""
    if is_walking(player):
        player.walk_distance += abs(player.vx) * dt
    else:
        # Standing or in the air: the next walk starts again from walk_1.
        player.walk_distance = 0.0


def frame_name(player, walk_frame_distance):
    """The name of the frame to draw ("idle", "walk_1", ...)."""
    if not player.on_ground:
        return JUMP_FRAME  # falls back to idle for a character without one
    if not is_walking(player):
        return "idle"
    step = int(player.walk_distance / walk_frame_distance)
    return WALK_CYCLE[step % len(WALK_CYCLE)]
