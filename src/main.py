import math

from pyray import *


def main():
    init_window(1280, 720, "My Python + Raylib game")

    player_pos = Vector2(0.0, 670.0)
    player_size = Vector2(50.0, 50.0)

    # Pixels per second
    speed = 400.0

    while not window_should_close():
        input_x = 0.0
        input_y = 0.0

        if is_key_down(KEY_UP):
            input_y -= 1.0
        if is_key_down(KEY_DOWN):
            input_y += 1.0
        if is_key_down(KEY_LEFT):
            input_x -= 1.0
        if is_key_down(KEY_RIGHT):
            input_x += 1.0

        # Normalize the direction so diagonal movement is not faster.
        input_length = math.hypot(input_x, input_y)
        if input_length > 0.0:
            distance = speed * get_frame_time()
            player_pos.x += input_x / input_length * distance
            player_pos.y += input_y / input_length * distance

        begin_drawing()
        clear_background(Color(160, 200, 255, 255))
        draw_rectangle_v(player_pos, player_size, BLUE)
        end_drawing()

    close_window()


if __name__ == "__main__":
    main()
