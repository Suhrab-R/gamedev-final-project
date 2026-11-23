"""Platformer physics for players, modelled on New Super Mario Bros. Wii.

What makes it feel like NSMBW:
- Walking speeds up to a walking top speed. Holding run keeps speeding up
  (more slowly) to a higher running top speed.
- Letting go of the direction keys slides to a stop. Pushing the other way
  skids, which stops you much faster than just letting go.
- Letting go of run while faster than walking speed slows you back down to
  walking speed instead of stopping instantly.
- A jump starts with a fixed upward speed, a little more the faster you are
  moving. While the jump button is held and you are still rising, gravity is
  much weaker, so holding the button longer gives a higher jump. Letting go
  switches to full gravity, which cuts the jump short.
- In the air you keep your momentum and can only steer a little, and you
  can't speed up past the speed you jumped at (holding run mid-air does
  nothing; only a running jump goes at running speed).

The numbers live in data/settings.json ("physics"): speeds in pixels per
second, accelerations in pixels per second squared. They approximate NSMBW's
per-frame values (the exact internal values aren't published), converted
with 1 block = 16 game units = 40 px (one 16 px sprite tile at scale 2.5)
at 60 frames per second.

Only the host runs this (in GameServer); clients just draw the results.
"""

from entities.player import hitbox_size


# The level editor's fly mode (a testing tool): pixels per second, and while holding run.
FLY_SPEED = 500
FLY_FAST_SPEED = 1200


def _fly(player, dt, settings, x_bounds):
    """Fly mode: move straight where WASD points, through everything."""
    speed = FLY_FAST_SPEED if player.run_held else FLY_SPEED
    player.vx = player.input_x * speed  # sent to clients for the facing/animation
    player.vy = 0.0
    if player.input_x != 0:
        player.facing = player.input_x
    player.x += player.input_x * speed * dt
    player.y += player.input_y * speed * dt
    width, height = hitbox_size(settings)
    world = settings["world"]
    player.x = _keep_inside(player, width, x_bounds)
    player.y = min(player.y, world["height"] - world["ground_height"] - height)  # not into the ground
    player.on_ground = False
    player.standing_on = None
    player.jump_was_held = player.jump_held


def approach(value, target, amount):
    """Move value toward target by at most amount, without going past it."""
    if value < target:
        return min(value + amount, target)
    return max(value - amount, target)


def step_player(player, dt, settings, platforms=(), x_bounds=None, ceiling_y=None, flat_floor=True):
    """Advance one player's physics by dt seconds, using their held buttons.

    platforms is the level's list (core/level.py). A platform with "solid"
    false is one-way (jump up through it, land on top); a solid one blocks
    you from every side. A None in the list is skipped (one that's off
    screen, or that this player passes through right now).

    x_bounds is (left, right): how far left the player's hitbox can go and how
    far right its right edge can go. None (the default) means the edges of
    the screen; a left of None means no left wall at all.

    ceiling_y, if given, is a ceiling the player's head can't go above (the
    runner level's top of the screen). Without one you can jump off the top.

    flat_floor: whether the ground strip along the bottom is a floor
    everywhere. Runner levels turn it off: their ground is solid platforms
    with gaps (pits) in it instead.
    """
    if x_bounds is None:
        x_bounds = (0.0, settings["world"]["width"])
    if player.flying:
        _fly(player, dt, settings, x_bounds)
        return
    physics = settings["physics"]
    _update_horizontal_speed(player, dt, physics)
    _update_vertical_speed(player, dt, physics)
    _move_and_collide(player, dt, settings, platforms, x_bounds, ceiling_y, flat_floor)
    # Remembered so next frame can tell a fresh jump press from a held button.
    player.jump_was_held = player.jump_held


def _update_horizontal_speed(player, dt, physics):
    direction = player.input_x  # -1 left, 0 none, 1 right
    if direction != 0:
        # Turn to face the held direction straight away (also mid-skid and
        # in the air), like Mario does.
        player.facing = direction
    # A level can make moving left faster ("left_speed_multiplier" in its
    # "physics"; level 2 uses it so backing away from obstacles is easier).
    # It scales the top speeds and how quickly you reach them.
    boost = physics.get("left_speed_multiplier", 1.0) if direction < 0 else 1.0
    walk_speed = physics["walk_speed"] * boost
    run_speed = physics["run_speed"] * boost
    max_speed = run_speed if player.run_held else walk_speed
    if not player.on_ground:
        # In the air the top speed can't go above what it was when you left
        # the ground, so pressing run mid-jump doesn't speed you up. (A
        # running jump keeps its running speed.)
        max_speed = min(max_speed, player.air_speed_cap * boost)

    if direction == 0:
        # No direction held: slide to a stop (barely slow down in the air).
        # "A stop" means moving with whatever you're standing on, so on a
        # runner level's moving obstacle you ease into riding along with it,
        # and after jumping off one you keep drifting with it. All speeds
        # here are speeds on the screen, so stepping onto or off a moving
        # obstacle never suddenly changes how fast you're going.
        target = player.ground_vx
        rate = physics["deceleration"] if player.on_ground else physics["air_deceleration"]
    elif player.vx * direction < 0:
        # Pushing against the way we're moving: skid (on the ground).
        target = direction * max_speed
        rate = physics["skid_deceleration"] if player.on_ground else physics["air_acceleration"]
    elif abs(player.vx) > max_speed:
        # Faster than allowed, e.g. run was just released: ease back down to
        # walking speed on the ground; keep the momentum in the air.
        target = direction * max_speed
        rate = physics["deceleration"] if player.on_ground else 0.0
    else:
        # Speeding up. Past walking speed, running builds up more slowly.
        target = direction * max_speed
        if not player.on_ground:
            rate = physics["air_acceleration"] * boost
        elif abs(player.vx) < walk_speed:
            rate = physics["walk_acceleration"] * boost
        else:
            rate = physics["run_acceleration"] * boost

    player.vx = approach(player.vx, target, rate * dt)

    if player.on_ground:
        # Remember the top speed for the air: walking speed, or more if we're
        # going faster than that. It stops updating the moment we leave the
        # ground (a jump or walking off a ledge), so it holds the take-off speed.
        player.air_speed_cap = max(physics["walk_speed"], abs(player.vx))


def _update_vertical_speed(player, dt, physics):
    # Jump only on a fresh press, so holding space doesn't keep bouncing.
    # The press is remembered for jump_buffer_time seconds ("jump buffering"),
    # so pressing jump just before landing still jumps as soon as you land.
    # Without this the press had to land on the exact frame you touch down.
    if player.jump_held and not player.jump_was_held:
        player.jump_buffer_left = physics["jump_buffer_time"]

    if player.jump_buffer_left > 0 and player.on_ground:
        # Faster movement gives a slightly stronger jump, like in NSMBW.
        # (Speed compared to what you're standing on, so just riding a moving
        # obstacle doesn't count as a running jump.)
        speed_fraction = min(abs(player.vx - player.ground_vx) / physics["run_speed"], 1.0)
        player.vy = -(physics["jump_speed"] + physics["jump_run_bonus"] * speed_fraction)
        player.on_ground = False
        player.jump_rising = True
        player.jump_buffer_left = 0.0
        player.jump_count = (player.jump_count + 1) % 256  # fits in one byte
    else:
        player.jump_buffer_left = max(0.0, player.jump_buffer_left - dt)

    # The weak "held jump" gravity ends for good once the button is released
    # or the jump reaches its peak; pressing again mid-air doesn't bring it back.
    if player.vy >= 0 or not player.jump_held:
        player.jump_rising = False

    gravity = physics["jump_hold_gravity"] if player.jump_rising else physics["gravity"]
    player.vy = min(player.vy + gravity * dt, physics["max_fall_speed"])


def _overlaps(player, width, height, box):
    """True if the player's hitbox and box ({"x", "y", "width", "height"}) overlap."""
    return (player.x < box["x"] + box["width"] and player.x + width > box["x"]
            and player.y < box["y"] + box["height"] and player.y + height > box["y"])


def _keep_inside(player, width, x_bounds):
    """The player's x, moved back inside x_bounds (see step_player) if needed."""
    left, right = x_bounds
    x = min(player.x, right - width)
    if left is not None:
        x = max(x, left)
    return x


def _move_and_collide(player, dt, settings, platforms, x_bounds, ceiling_y, flat_floor):
    world = settings["world"]
    width, height = hitbox_size(settings)
    present = [(index, platform) for index, platform in enumerate(platforms) if platform is not None]
    solid = [(index, platform) for index, platform in present if platform["solid"]]
    one_way = [(index, platform) for index, platform in present if not platform["solid"]]

    old_bottom = player.y + height  # where the feet were before this frame's move

    # Move sideways first and fix any overlap with a solid platform, then move
    # up/down and fix that. Doing one axis at a time means we always know which
    # way to push the player out (sideways after the sideways move, up/down
    # after the vertical one), so running into a block's side can't teleport
    # you on top of it.
    player.x += player.vx * dt

    # The screen edges (x_bounds) act as walls.
    inside_x = _keep_inside(player, width, x_bounds)
    if inside_x != player.x:
        player.x = inside_x
        player.vx = 0.0

    # Solid platforms, sideways: push the player back out of the side they're on.
    # (Comparing centers instead of using vx also works if the player was put
    # inside one without moving, e.g. a platform placed on top of them.)
    # Speed is only stopped if the player is moving into the platform. If it
    # is the platform that moved into them (a runner obstacle pushing them
    # left), they keep their speed, so they can still run away from it.
    for _, platform in solid:
        if _overlaps(player, width, height, platform):
            if player.x + width / 2 < platform["x"] + platform["width"] / 2:
                player.x = platform["x"] - width  # pushed out to the left
                player.vx = min(player.vx, 0.0)
            else:
                player.x = platform["x"] + platform["width"]  # pushed out to the right
                player.vx = max(player.vx, 0.0)

    player.y += player.vy * dt

    # Most levels have no ceiling (they go above the top of the screen).
    if ceiling_y is not None and player.y < ceiling_y:
        player.y = ceiling_y
        player.vy = 0.0
        player.jump_rising = False

    player.on_ground = False
    player.standing_on = None

    # Solid platforms, up/down: falling onto one lands on top, jumping into
    # one from below bumps your head.
    for index, platform in solid:
        if _overlaps(player, width, height, platform):
            if player.vy >= 0:
                player.y = platform["y"] - height
                player.on_ground = True
                player.standing_on = index  # enemies use this to notice players
            else:
                player.y = platform["y"] + platform["height"]
                player.jump_rising = False
            player.vy = 0.0

    # One-way platforms (like NSMBW's sky platforms): you can jump up through
    # them from below and land on top. A player only lands while falling, and
    # only if their feet were at or above the platform's top last frame and
    # are at or below it now, i.e. they crossed the top this frame.
    if player.vy >= 0 and not player.on_ground:
        new_bottom = player.y + height
        for index, platform in one_way:
            top = platform["y"]
            overlaps = player.x < platform["x"] + platform["width"] and player.x + width > platform["x"]
            if overlaps and old_bottom <= top <= new_bottom:
                player.y = top - height
                player.vy = 0.0
                player.on_ground = True
                player.standing_on = index
                break

    # The ground strip along the bottom of the screen.
    floor_y = world["height"] - world["ground_height"] - height
    if flat_floor and player.y >= floor_y:
        player.y = floor_y
        player.vy = 0.0
        player.on_ground = True
