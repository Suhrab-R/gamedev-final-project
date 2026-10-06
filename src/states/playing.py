"""State 2: in the game, moving around with the other players.

Each frame the held keys go to the host (straight into the server on the
host's own computer, over UDP from a client). Every player is drawn where
the host says they are: on the host that is the server's own data, on a
client it is the newest snapshot.
"""

from pyray import *

from core.state_machine import GameState
from ui.draw import (
    BACKGROUND_COLOR, MUTED_TEXT_COLOR, TEAM_COLORS, TEXT_COLOR,
    draw_character, draw_disconnected_overlay, draw_text_centered,
)

# Show a hint if no positions have arrived after this many seconds.
NO_DATA_WARNING_SECONDS = 2.0


def read_movement_input():
    """Return the (x, y) direction being held, each -1, 0 or 1. WASD or arrows."""
    input_x = 0
    input_y = 0
    if is_key_down(KeyboardKey.KEY_W) or is_key_down(KeyboardKey.KEY_UP):
        input_y -= 1
    if is_key_down(KeyboardKey.KEY_S) or is_key_down(KeyboardKey.KEY_DOWN):
        input_y += 1
    if is_key_down(KeyboardKey.KEY_A) or is_key_down(KeyboardKey.KEY_LEFT):
        input_x -= 1
    if is_key_down(KeyboardKey.KEY_D) or is_key_down(KeyboardKey.KEY_RIGHT):
        input_x += 1
    return input_x, input_y


class PlayingState(GameState):
    def enter(self):
        self.time_in_state = 0.0

    def update(self, dt):
        self.time_in_state += dt
        # Send this frame's keys. The host moves us; we just draw the result.
        input_x, input_y = read_movement_input()
        self.game.session.send_input(input_x, input_y)

    def render(self):
        game = self.game
        session = game.session
        clear_background(BACKGROUND_COLOR)

        self._draw_players()
        self._draw_hud()

        if not session.has_positions and self.time_in_state > NO_DATA_WARNING_SECONDS:
            draw_text_centered("Waiting for game data from the host (is UDP blocked by a firewall?)",
                               game.screen_width / 2, game.screen_height / 2, 24, TEXT_COLOR)

        if session.disconnect_reason:
            draw_disconnected_overlay(session.disconnect_reason, game.screen_width, game.screen_height)

    def _draw_players(self):
        game = self.game
        my_id = game.session.my_id
        size = game.settings["player"]["size"]
        shapes = {character["id"]: character["shape"] for character in game.characters}

        others = []
        me = None
        for player in game.session.players.values():
            if player.character is None:
                continue  # still choosing a character
            if player.id == my_id:
                me = player
            else:
                others.append(player)

        # Draw ourselves last so we are always on top.
        if me is not None:
            others.append(me)

        for player in others:
            draw_character(shapes.get(player.character, "square"), player.x, player.y, size, player.team)

            label = "YOU" if player.id == my_id else f"P{player.id}"
            if player.is_host:
                label += " (HOST)"
            draw_text_centered(label, player.x + size / 2, player.y - 22, 16, TEXT_COLOR)

    def _draw_hud(self):
        game = self.game
        session = game.session
        draw_text(f"TEAM {session.my_team.upper()}", 20, 20, 28, TEAM_COLORS[session.my_team])
        draw_text(f"Players online: {len(session.players)}", 20, 56, 20, TEXT_COLOR)
        me = game.my_player()
        if me is not None and me.is_host:
            draw_text(f"Hosting on {session.lan_ip}", 20, game.screen_height - 36, 20, MUTED_TEXT_COLOR)
        draw_text_centered("WASD or arrow keys to move", game.screen_width / 2,
                           game.screen_height - 36, 20, MUTED_TEXT_COLOR)
