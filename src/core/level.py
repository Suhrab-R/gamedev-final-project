"""Levels: the layout files data/level1.json, data/level2.json, ...

Every level has:

    mode       "climb"  (level 1): the teams climb up, each with its own camera
               "runner" (level 2): the screen stays still and the obstacles
               slide in from the right; players dodge them
    platforms  [{"x", "y", "width", "height", "solid"}]   pixels, x/y = top-left corner
               solid false = one-way (jump up through it, land on top),
               solid true  = solid from every side (you can only get on top from above)
    enemies    [{"platform", "x", "kind"}]   platform = index into platforms,
               x = the center of where it starts, kind = "regular" (only walks back and forth)
               or "chaser" (also chases players who land on its platform)
    flag       {"x", "y"} or null   top-left corner; touching it completes the level
    decorations [{"x", "y", "width", "height"}]   see-through rectangles that
               don't collide with anything, for drawing arrows and other
               hints to players out of blocks
    physics    (optional) {"walk_speed": ..., ...}   movement values for this
               level only, replacing the same ones in settings.json "physics".
               It can also have "left_speed_multiplier": moving left is that
               many times faster (1.2 = 20% faster)

A runner level's platforms are its obstacles, laid out along a long course:
an obstacle at course x reaches the screen once the course has scrolled far
enough (it is drawn at x - scroll_x). So obstacles come in the order they
are placed along the course. A runner level also has:

    length     how long the course is (how far it scrolls), in pixels
    scroll     {"start_speed", "end_speed"}   pixels per second; the obstacles
               speed up steadily from one to the other over the course
    pits       [{"x", "width"}]   stretches of the course with no ground: fall in
               and you go back to the last platform you stood on
    split      {"y", "height", "until"}   the middle floor that keeps the teams
               apart: blue runs on top of it, red on the ground below. It
               slides away like an obstacle, ending "until" of the way through
               the course (0.72 = 72%); after that both teams share the screen.

Only the host reads the file. It sends the level to every client over TCP, so
everyone plays the same level even if their own copy of the file differs.
"""

import json

from core.settings import DATA_DIR

CLIMB = "climb"
RUNNER = "runner"

REGULAR = "regular"
CHASER = "chaser"
ENEMY_KINDS = (REGULAR, CHASER)  # snapshots send the kind as its index in this tuple

# The flag's size in blocks (world.block_size): a pole one block wide, three tall.
FLAG_WIDTH_BLOCKS = 1
FLAG_HEIGHT_BLOCKS = 3

# What a runner level uses for anything its file leaves out.
RUNNER_DEFAULTS = {
    "length": 12000,
    "scroll": {"start_speed": 160, "end_speed": 280},
    "split": {"y": 400, "height": 40, "until": 0.72},
}


def level_path(file_name):
    return DATA_DIR / file_name


def load_level(file_name):
    """Read a level file from data/, filling in anything left out (see clean_level).

    Raises OSError or ValueError (json.JSONDecodeError is one) if the file
    can't be read or isn't valid JSON.
    """
    with open(level_path(file_name), encoding="utf-8") as file:
        return clean_level(json.load(file))


def clean_level(level):
    """Return a copy of level with defaults filled in and broken entries dropped.

    This lets the level file be edited by hand: a platform without "solid" is
    one-way, an enemy without "x" starts in the middle of its platform, and an
    enemy whose platform doesn't exist is left out instead of crashing.
    """
    platforms = []
    for data in level.get("platforms", []):
        platforms.append({
            "x": data["x"], "y": data["y"], "width": data["width"], "height": data["height"],
            "solid": bool(data.get("solid", False)),
        })

    enemies = []
    for data in level.get("enemies", []):
        index = data.get("platform")
        if not isinstance(index, int) or not 0 <= index < len(platforms):
            continue
        platform = platforms[index]
        kind = data.get("kind", CHASER)
        enemies.append({
            "platform": index,
            "x": data.get("x", platform["x"] + platform["width"] / 2),
            "kind": kind if kind in ENEMY_KINDS else CHASER,
        })

    flag = level.get("flag")
    if flag is not None:
        flag = {"x": flag["x"], "y": flag["y"]}
    decorations = [{"x": d["x"], "y": d["y"], "width": d["width"], "height": d["height"]}
                   for d in level.get("decorations", [])]

    cleaned = {"mode": RUNNER if level.get("mode") == RUNNER else CLIMB,
               "platforms": platforms, "enemies": enemies, "flag": flag,
               "decorations": decorations, "physics": dict(level.get("physics", {}))}
    if cleaned["mode"] == RUNNER:
        cleaned["pits"] = [{"x": pit["x"], "width": pit["width"]} for pit in level.get("pits", [])]
        cleaned["length"] = level.get("length", RUNNER_DEFAULTS["length"])
        cleaned["scroll"] = dict(RUNNER_DEFAULTS["scroll"], **level.get("scroll", {}))
        cleaned["split"] = dict(RUNNER_DEFAULTS["split"], **level.get("split", {}))
    return cleaned


def save_level(level, file_name):
    """Write the level to its file in data/, one platform or enemy per line
    so it stays easy to read and edit by hand."""
    def json_list(items):
        if not items:
            return "[]"
        return "[\n" + ",\n".join("    " + json.dumps(item) for item in items) + "\n  ]"

    lines = [f'  "mode": {json.dumps(level["mode"])}']
    if level["physics"]:
        lines.append(f'  "physics": {json.dumps(level["physics"])}')
    if level["mode"] == RUNNER:
        lines += [f'  "length": {json.dumps(level["length"])}',
                  f'  "scroll": {json.dumps(level["scroll"])}',
                  f'  "split": {json.dumps(level["split"])}',
                  f'  "pits": {json_list(level["pits"])}']
    lines += [f'  "platforms": {json_list(level["platforms"])}',
              f'  "enemies": {json_list(level["enemies"])}',
              f'  "decorations": {json_list(level["decorations"])}',
              f'  "flag": {json.dumps(level["flag"])}']
    with open(level_path(file_name), "w", encoding="utf-8") as file:
        file.write("{\n" + ",\n".join(lines) + "\n}\n")


def split_end_x(level):
    """Where a runner level's middle floor ends (the teams merge after it)."""
    return level["length"] * level["split"]["until"]


def all_platforms(level, world=None):
    """Every platform players collide with: the level's own, plus in a runner
    level the middle floor and the ground (added at the end, so enemy
    platform indices still point at the level's own platforms).

    A runner level's ground is made of solid pieces with gaps where its pits
    are, so players can fall in (climb levels use the physics' flat floor).
    world is settings["world"], needed for where the ground is.
    """
    if level["mode"] != RUNNER:
        return level["platforms"]
    split = level["split"]
    middle_floor = {"x": -10000, "y": split["y"], "width": split_end_x(level) + 10000,
                    "height": split["height"], "solid": True}
    return level["platforms"] + [middle_floor] + ground_pieces(level, world)


def ground_pieces(level, world):
    """A runner level's ground: solid blocks along the bottom with a gap at
    each pit. Marked "ground" so they're drawn as ground, not as platforms."""
    top = world["height"] - world["ground_height"]
    pieces = []
    x = -10000  # well past the start of the course
    for pit in sorted(level["pits"], key=lambda pit: pit["x"]):
        if pit["x"] > x:
            pieces.append({"x": x, "y": top, "width": pit["x"] - x, "height": world["ground_height"],
                           "solid": True, "ground": True})
        x = max(x, pit["x"] + pit["width"])
    end = level["length"] + 20000  # well past the end of the course
    pieces.append({"x": x, "y": top, "width": end - x, "height": world["ground_height"],
                   "solid": True, "ground": True})
    return pieces


# How far outside the screen something can be and still count as "in view"
# (so things that are about to come on screen are already there).
VIEW_MARGIN = 200


def in_view(x, y, width, height, view_left, view_top, view_width, view_height):
    """True if the box at (x, y) is at least partly inside the view whose
    top-left corner is (view_left, view_top), give or take VIEW_MARGIN."""
    return (x + width >= view_left - VIEW_MARGIN and x <= view_left + view_width + VIEW_MARGIN
            and y + height >= view_top - VIEW_MARGIN and y <= view_top + view_height + VIEW_MARGIN)


def platforms_in_view(level, world, scroll_x, view_top, view_width, view_height):
    """Every platform (all_platforms) where it is on screen, for the physics.

    Runner levels: the course has scrolled scroll_x to the left, so each
    platform is moved by that much. Climb levels: view_top is the team's
    camera height. Platforms outside the view are None instead, so the
    physics skips them rather than checking every player against the whole
    level every frame. The list keeps the same order and length, so a
    platform's index means the same platform every frame (enemies and
    "the last platform I stood on" rely on that).
    """
    result = []
    for platform in all_platforms(level, world):
        x = platform["x"] - scroll_x
        if not in_view(x, platform["y"], platform["width"], platform["height"],
                       0, view_top, view_width, view_height):
            result.append(None)
        elif scroll_x == 0:
            result.append(platform)  # not moved, so no copy needed
        else:
            result.append(dict(platform, x=x))
    return result


def flag_rect(flag, settings):
    """The flag's (x, y, width, height) in pixels."""
    block = settings["world"]["block_size"]
    return flag["x"], flag["y"], FLAG_WIDTH_BLOCKS * block, FLAG_HEIGHT_BLOCKS * block


def rects_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    """True if two rectangles (top-left x, y, width, height) overlap."""
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by
