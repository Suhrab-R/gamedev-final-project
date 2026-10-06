"""Colors and drawing helpers used by every screen.

Characters are placeholder shapes for now. Every character's hitbox is the
same size x size square; the shape is just drawn inside it, so swapping in
sprites later won't change gameplay.
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

OUTLINE_THICKNESS = 3.0


def draw_character(shape, x, y, size, team):
    """Draw a character's shape filling the size x size box at (x, y)."""
    fill = TEAM_COLORS[team]
    outline = TEAM_OUTLINE_COLORS[team]

    if shape == "circle":
        center = Vector2(x + size / 2, y + size / 2)
        radius = size / 2
        draw_circle_v(center, radius, fill)
        draw_ring(center, radius - OUTLINE_THICKNESS, radius, 0, 360, 48, outline)
    elif shape == "triangle":
        top = Vector2(x + size / 2, y)
        bottom_left = Vector2(x, y + size)
        bottom_right = Vector2(x + size, y + size)
        # raylib needs triangle points in counter-clockwise order.
        draw_triangle(top, bottom_left, bottom_right, fill)
        draw_line_ex(top, bottom_left, OUTLINE_THICKNESS, outline)
        draw_line_ex(bottom_left, bottom_right, OUTLINE_THICKNESS, outline)
        draw_line_ex(bottom_right, top, OUTLINE_THICKNESS, outline)
    else:  # "square" and any unknown shape
        box = Rectangle(x, y, size, size)
        draw_rectangle_rec(box, fill)
        draw_rectangle_lines_ex(box, OUTLINE_THICKNESS, outline)


def draw_text_centered(text, center_x, y, font_size, color):
    """Draw text horizontally centered on center_x."""
    width = measure_text(text, font_size)
    draw_text(text, int(center_x - width / 2), int(y), font_size, color)


def draw_disconnected_overlay(reason, screen_width, screen_height):
    """Dim the screen and explain that the connection to the server is gone."""
    draw_rectangle(0, 0, screen_width, screen_height, Color(0, 0, 0, 170))
    draw_text_centered(reason, screen_width / 2, screen_height / 2 - 30, 30, RAYWHITE)
    draw_text_centered("Close the window and start the game again to reconnect.",
                       screen_width / 2, screen_height / 2 + 15, 20, LIGHTGRAY)
