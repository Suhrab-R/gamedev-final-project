"""Colors and drawing helpers used by every screen.

Every character's hitbox is the same width x height upright rectangle.
Sprite characters are drawn standing on the bottom of that box; placeholder
shapes are drawn filling it. Either way the look never changes gameplay.
"""

from pyray import *

from entities.player import TEAM_BLUE, TEAM_RED

BACKGROUND_COLOR = Color(235, 236, 242, 255)
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

# The level: a faint block grid (to judge jump heights by eye) and the ground.
GRID_COLOR = Color(222, 223, 232, 255)
GROUND_COLOR = Color(150, 105, 70, 255)
GROUND_TOP_COLOR = Color(90, 160, 70, 255)

OUTLINE_THICKNESS = 3.0


def draw_character(texture, x, y, width, height, team, facing, sprite_scale):
    """Draw a character in the width x height box at (x, y).

    texture is the character's sprite for this team, or None for characters
    without one (and if a sprite failed to load); those get a rectangle.
    """
    if texture is not None:
        draw_sprite(texture, x, y, width, height, facing, sprite_scale)
    else:
        draw_placeholder(x, y, width, height, team)


def draw_sprite(texture, x, y, width, height, facing, scale):
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
    draw_texture_pro(texture, source, dest, Vector2(0, 0), 0, WHITE)


def draw_placeholder(x, y, width, height, team):
    """Draw a team-colored rectangle filling the width x height box at (x, y)."""
    box = Rectangle(x, y, width, height)
    draw_rectangle_rec(box, TEAM_COLORS[team])
    draw_rectangle_lines_ex(box, OUTLINE_THICKNESS, TEAM_OUTLINE_COLORS[team])


def draw_level(world):
    """Draw the block grid and the ground strip along the bottom."""
    block = world["block_size"]
    for grid_x in range(0, world["width"], block):
        draw_line(grid_x, 0, grid_x, world["height"], GRID_COLOR)
    for grid_y in range(0, world["height"], block):
        draw_line(0, grid_y, world["width"], grid_y, GRID_COLOR)

    ground_top = world["height"] - world["ground_height"]
    draw_rectangle(0, ground_top, world["width"], world["ground_height"], GROUND_COLOR)
    draw_rectangle(0, ground_top, world["width"], 8, GROUND_TOP_COLOR)


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
