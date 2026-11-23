"""Colors and drawing helpers used by every screen.

Every character's hitbox is the same width x height upright rectangle.
Sprite characters are drawn standing on the bottom of that box; placeholder
shapes are drawn filling it. Either way the look never changes gameplay.
"""

from pyray import *

from entities.enemy import CHASE, PATROL
from entities.player import TEAM_BLUE, TEAM_RED

BACKGROUND_COLOR = Color(222, 240, 252, 255)  # very light sky blue
TEXT_COLOR = Color(35, 35, 45, 255)
MUTED_TEXT_COLOR = Color(110, 110, 125, 255)

TEAM_COLORS = {
    TEAM_BLUE: Color(45, 110, 230, 255),
    TEAM_RED: Color(220, 55, 55, 255),
}
TEAM_OUTLINE_COLORS = {
    TEAM_BLUE: Color(20, 50, 120, 255),
    TEAM_RED: Color(110, 20, 20, 255),
}

# The level: the ground, the platforms and the flag. (The block grid is only
# drawn in the level editor.)
GRID_COLOR = Color(215, 216, 228, 255)
GROUND_COLOR = Color(150, 105, 70, 255)
GROUND_TOP_COLOR = Color(90, 160, 70, 255)

# One-way platforms are wooden planks; solid ones are grey stone.
PLATFORM_COLOR = Color(176, 124, 84, 255)
PLATFORM_TOP_COLOR = Color(222, 178, 120, 255)
SOLID_COLOR = Color(120, 120, 135, 255)
SOLID_TOP_COLOR = Color(160, 160, 175, 255)
SOLID_OUTLINE_COLOR = Color(60, 60, 72, 255)

# Decorations (see-through, no collision): a warm amber, easy to spot on the
# sky blue without hiding anything behind it.
DECORATION_COLOR = Color(255, 165, 20, 140)

FLAG_POLE_COLOR = Color(90, 90, 100, 255)
FLAG_COLOR = Color(40, 180, 70, 255)
FLAG_OUTLINE_COLOR = Color(15, 90, 35, 255)

# An enemy whose sprite failed to load is drawn as a square in its state's color.
ENEMY_COLORS = {
    PATROL: Color(230, 41, 55, 255),  # red
    CHASE: Color(120, 0, 15, 255),  # darker red
}
ENEMY_OUTLINE_COLOR = Color(60, 0, 8, 255)

OUTLINE_THICKNESS = 3.0


def draw_character(texture, x, y, width, height, team, facing, sprite_scale, tint=WHITE):
    """Draw a character in the width x height box at (x, y).

    texture is the character's sprite for this team, or None for characters
    without one (and if a sprite failed to load); those get a rectangle.
    tint colors the sprite (WHITE = as drawn; a lower alpha = see-through).
    """
    if texture is not None:
        draw_sprite(texture, x, y, width, height, facing, sprite_scale, tint)
    else:
        draw_placeholder(x, y, width, height, team)


def draw_sprite(texture, x, y, width, height, facing, scale, tint=WHITE):
    """Draw a sprite scaled up, centered on the box and standing on its bottom.

    The image faces right. A negative source width makes raylib draw it
    mirrored, so facing left needs no second image.
    """
    sprite_width = texture.width * scale
    sprite_height = texture.height * scale
    # Whole-pixel position so the scaled-up pixel art stays crisp.
    left = round(x + width / 2 - sprite_width / 2)
    top = round(y + height - sprite_height)
    source = Rectangle(0, 0, texture.width * facing, texture.height)
    dest = Rectangle(left, top, sprite_width, sprite_height)
    draw_texture_pro(texture, source, dest, Vector2(0, 0), 0, tint)


def draw_placeholder(x, y, width, height, team):
    """Draw a team-colored rectangle filling the width x height box at (x, y)."""
    box = Rectangle(x, y, width, height)
    draw_rectangle_rec(box, TEAM_COLORS[team])
    draw_rectangle_lines_ex(box, OUTLINE_THICKNESS, TEAM_OUTLINE_COLORS[team])


def draw_grid(world, view_left, view_top):
    """A faint block grid (block_size), to line things up by eye, covering
    the screen's worth of world whose top-left corner is (view_left, view_top)."""
    block = world["block_size"]
    first_x = int(view_left // block) * block  # the grid lines at or before the view's edges
    first_y = int(view_top // block) * block
    right = int(view_left + world["width"])
    bottom = int(view_top + world["height"])
    for grid_x in range(first_x, right + 1, block):
        draw_line(grid_x, first_y, grid_x, bottom, GRID_COLOR)
    for grid_y in range(first_y, bottom + 1, block):
        draw_line(first_x, grid_y, right, grid_y, GRID_COLOR)


def draw_level(world, platforms, decorations, flag_area, view_left=0, ground_strip=True):
    """Draw the ground strip along the bottom, the decorations, the platforms
    and the flag.

    platforms and decorations are the ones to draw (in level coordinates),
    flag_area is the flag's (x, y, width, height) or None if there's no flag,
    and view_left is the level x at the left of the screen (runner levels
    scroll), so the ground covers whatever part of the level is on screen.
    ground_strip=False leaves the strip out: runner levels' ground comes in
    pieces (with gaps for pits) among the platforms instead.
    """
    if ground_strip:
        ground_top = world["height"] - world["ground_height"]
        left = int(view_left)
        draw_rectangle(left, ground_top, world["width"] + 1, world["ground_height"], GROUND_COLOR)
        draw_rectangle(left, ground_top, world["width"] + 1, 7, GROUND_TOP_COLOR)

    # Decorations first, so they sit behind the platforms instead of tinting them.
    for decoration in decorations:
        draw_rectangle(int(decoration["x"]), int(decoration["y"]), int(decoration["width"]),
                       int(decoration["height"]), DECORATION_COLOR)
    for platform in platforms:
        draw_platform(platform)
    if flag_area is not None:
        draw_flag(*flag_area)


def draw_platform(platform):
    x, y, width, height = int(platform["x"]), int(platform["y"]), int(platform["width"]), int(platform["height"])
    if platform.get("ground"):  # a piece of a runner level's ground
        draw_rectangle(x, y, width, height, GROUND_COLOR)
        draw_rectangle(x, y, width, 7, GROUND_TOP_COLOR)
    elif platform["solid"]:
        draw_rectangle(x, y, width, height, SOLID_COLOR)
        draw_rectangle(x, y, width, 5, SOLID_TOP_COLOR)
        draw_rectangle_lines_ex(Rectangle(x, y, width, height), 2.0, SOLID_OUTLINE_COLOR)
    else:
        draw_rectangle(x, y, width, height, PLATFORM_COLOR)
        draw_rectangle(x, y, width, 5, PLATFORM_TOP_COLOR)


def draw_flag(x, y, width, height):
    """A goal flag filling the width x height box: a pole with a ball on top
    and a green pennant pointing right."""
    pole_x = x + width * 0.25
    ball_radius = width * 0.15
    draw_rectangle(int(pole_x - 2), int(y + ball_radius), 4, int(height - ball_radius), FLAG_POLE_COLOR)
    draw_circle(int(pole_x), int(y + ball_radius), ball_radius, FLAG_POLE_COLOR)
    top = Vector2(pole_x + 2, y + ball_radius * 2)
    bottom = Vector2(pole_x + 2, y + ball_radius * 2 + height * 0.3)
    tip = Vector2(x + width, y + ball_radius * 2 + height * 0.15)
    draw_triangle(top, bottom, tip, FLAG_COLOR)  # points must go counter-clockwise
    draw_triangle_lines(top, bottom, tip, FLAG_OUTLINE_COLOR)


def draw_enemy(enemy, size, texture, scale):
    """Draw an enemy: its sprite standing on the bottom of its size x size
    box, or, if the sprite failed to load, a square colored by its AI state."""
    if texture is not None:
        draw_sprite(texture, enemy.x, enemy.y, size, size, 1, scale)
        return
    box = Rectangle(enemy.x, enemy.y, size, size)
    draw_rectangle_rec(box, ENEMY_COLORS[enemy.state])
    draw_rectangle_lines_ex(box, OUTLINE_THICKNESS, ENEMY_OUTLINE_COLOR)


PROGRESS_BAR_COLOR = Color(255, 255, 255, 200)
PROGRESS_BAR_OUTLINE_COLOR = Color(70, 80, 100, 255)


def draw_progress_bar(center_x, top, bottom, progress_by_team):
    """A vertical bar from the start (bottom) to the flag (top), with each
    team's arrow beside it pointing in at the bar: blue on the left, red on
    the right.

    progress_by_team: team -> 0.0 (start) .. 1.0 (at the flag), or None for
    a team with nobody in the game (no arrow is drawn).
    """
    bar_width = 10
    bar = Rectangle(center_x - bar_width / 2, top, bar_width, bottom - top)
    draw_rectangle_rec(bar, PROGRESS_BAR_COLOR)
    draw_rectangle_lines_ex(bar, 2, PROGRESS_BAR_OUTLINE_COLOR)
    # A small flag above the bar marks the goal end.
    draw_flag(center_x - 4, top - 34, 22, 30)

    arrow_length = 22
    arrow_half_height = 11
    gap = 4  # between the arrow's tip and the bar
    for team, progress in progress_by_team.items():
        if progress is None:
            continue
        y = bottom - progress * (bottom - top)
        if team == TEAM_BLUE:
            tip_x = center_x - bar_width / 2 - gap  # on the left, pointing right
            base_x = tip_x - arrow_length
            # draw_triangle wants its corners counter-clockwise (as seen on screen).
            corners = (Vector2(base_x, y - arrow_half_height), Vector2(base_x, y + arrow_half_height),
                       Vector2(tip_x, y))
        else:
            tip_x = center_x + bar_width / 2 + gap  # on the right, pointing left
            base_x = tip_x + arrow_length
            corners = (Vector2(base_x, y + arrow_half_height), Vector2(base_x, y - arrow_half_height),
                       Vector2(tip_x, y))
        draw_triangle(*corners, TEAM_COLORS[team])
        draw_triangle_lines(*corners, TEAM_OUTLINE_COLORS[team])


def draw_runner_progress_bar(left, right, floor_y, floor_height, progress):
    """The runner level's progress bar: lying inside the middle floor (the
    floor_height-tall strip at floor_y) from left (start) to right (end of
    the course). Both teams are at the same point (they dodge the same
    obstacles), so blue's arrow sits above the bar pointing down at it and
    red's below pointing up, side by side."""
    center_y = floor_y + floor_height / 2
    bar_height = 8
    bar = Rectangle(left, center_y - bar_height / 2, right - left, bar_height)
    draw_rectangle_rec(bar, PROGRESS_BAR_COLOR)
    draw_rectangle_lines_ex(bar, 2, PROGRESS_BAR_OUTLINE_COLOR)
    draw_flag(right + 6, center_y - 22, 18, 26)  # the goal end

    x = left + progress * (right - left)
    half_width = 9
    gap = 2  # between an arrow's tip and the bar
    top_of_bar = center_y - bar_height / 2
    bottom_of_bar = center_y + bar_height / 2
    arrow_length = (floor_height - bar_height) / 2 - gap - 1  # fits inside the floor
    # draw_triangle wants its corners counter-clockwise (as seen on screen).
    blue = (Vector2(x - half_width, top_of_bar - gap - arrow_length), Vector2(x, top_of_bar - gap),
            Vector2(x + half_width, top_of_bar - gap - arrow_length))
    red = (Vector2(x + half_width, bottom_of_bar + gap + arrow_length), Vector2(x, bottom_of_bar + gap),
           Vector2(x - half_width, bottom_of_bar + gap + arrow_length))
    for team, corners in ((TEAM_BLUE, blue), (TEAM_RED, red)):
        draw_triangle(*corners, TEAM_COLORS[team])
        draw_triangle_lines(*corners, TEAM_OUTLINE_COLORS[team])


def draw_banner(title, subtitle, color, screen_width, screen_height):
    """A big message across the middle of the screen (e.g. "LEVEL COMPLETE!")."""
    height = 130
    top = screen_height / 2 - height / 2
    draw_rectangle(0, int(top), screen_width, height, Color(20, 20, 28, 230))
    draw_text_centered(title, screen_width / 2, top + 18, 56, color)
    draw_text_centered(subtitle, screen_width / 2, top + 86, 24, RAYWHITE)


def draw_text_centered(text, center_x, y, font_size, color):
    """Draw text horizontally centered on center_x."""
    width = measure_text(text, font_size)
    draw_text(text, int(center_x - width / 2), int(y), font_size, color)


def draw_notice(text, screen_width, screen_height):
    """A short message in a dark box near the bottom of the screen."""
    font_size = 20
    padding = 10
    width = measure_text(text, font_size) + padding * 2
    x = (screen_width - width) / 2
    y = screen_height - 60
    draw_rectangle(int(x), int(y), int(width), font_size + padding * 2, Color(0, 0, 0, 190))
    draw_text(text, int(x + padding), int(y + padding), font_size, RAYWHITE)


def draw_disconnected_overlay(reason, screen_width, screen_height):
    """Dim the screen and explain that the connection to the server is gone."""
    draw_rectangle(0, 0, screen_width, screen_height, Color(0, 0, 0, 170))
    draw_text_centered(reason, screen_width / 2, screen_height / 2 - 30, 30, RAYWHITE)
    draw_text_centered("Close the window and start the game again to reconnect.",
                       screen_width / 2, screen_height / 2 + 15, 20, LIGHTGRAY)
