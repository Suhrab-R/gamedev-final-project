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
- In the air you keep your momentum and can only steer a little.

The numbers live in data/settings.json ("physics"): speeds in pixels per
second, accelerations in pixels per second squared. They approximate NSMBW's
per-frame values (the exact internal values aren't published), converted
with 1 block = 16 game units = 48 px at 60 frames per second.

Only the host runs this (in GameServer); clients just draw the results.
"""


def approach(value, target, amount):
    """Move value toward target by at most amount, without going past it."""
    if value < target:
        return min(value + amount, target)
    return max(value - amount, target)


def step_player(player, dt, settings):
    """Advance one player's physics by dt seconds, using their held buttons."""
    physics = settings["physics"]
    _update_horizontal_speed(player, dt, physics)
    _update_vertical_speed(player, dt, physics)
    _move_and_collide(player, dt, settings)
    # Remembered so next frame can tell a fresh jump press from a held button.
    player.jump_was_held = player.jump_held


def _update_horizontal_speed(player, dt, physics):
    direction = player.input_x  # -1 left, 0 none, 1 right
    if direction != 0:
        # Turn to face the held direction straight away (also mid-skid and
        # in the air), like Mario does.
        player.facing = direction
    max_speed = physics["run_speed"] if player.run_held else physics["walk_speed"]

    if direction == 0:
        # No direction held: slide to a stop (barely slow down in the air).
        target = 0.0
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
            rate = physics["air_acceleration"]
        elif abs(player.vx) < physics["walk_speed"]:
            rate = physics["walk_acceleration"]
        else:
            rate = physics["run_acceleration"]

    player.vx = approach(player.vx, target, rate * dt)


def _update_vertical_speed(player, dt, physics):
    # Jump only on a fresh press, so holding space doesn't keep bouncing.
    # The press is remembered for jump_buffer_time seconds ("jump buffering"),
    # so pressing jump just before landing still jumps as soon as you land.
    # Without this the press had to land on the exact frame you touch down.
    if player.jump_held and not player.jump_was_held:
        player.jump_buffer_left = physics["jump_buffer_time"]

    if player.jump_buffer_left > 0 and player.on_ground:
        # Faster movement gives a slightly stronger jump, like in NSMBW.
        speed_fraction = min(abs(player.vx) / physics["run_speed"], 1.0)
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


def _move_and_collide(player, dt, settings):
    world = settings["world"]
    width = settings["player"]["width"]
    height = settings["player"]["height"]

    player.x += player.vx * dt
    player.y += player.vy * dt

    # Screen edges act as walls.
    if player.x < 0:
        player.x = 0.0
        player.vx = 0.0
    elif player.x > world["width"] - width:
        player.x = world["width"] - width
        player.vx = 0.0

    # Top of the screen acts as a ceiling.
    if player.y < 0:
        player.y = 0.0
        player.vy = 0.0
        player.jump_rising = False

    # The ground strip along the bottom of the screen.
    floor_y = world["height"] - world["ground_height"] - height
    if player.y >= floor_y:
        player.y = floor_y
        player.vy = 0.0
        player.on_ground = True
    else:
        player.on_ground = False
