"""State 2: in the game, moving around with the other players.

Each frame we send the held keys to the server as a command and move our own
player straight away (prediction, see net/client_sync.py). Everyone else is
drawn at the newest position from the server's snapshots.
"""

from pyray import *

from core.state_machine import GameState
from net import protocol
from ui.draw import (
    BACKGROUND_COLOR, MUTED_TEXT_COLOR, TEAM_COLORS, TEXT_COLOR,
    draw_character, draw_disconnected_overlay, draw_text_centered,
)

# Show a hint if no game data has arrived after this many seconds.
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
        game = self.game
        self.time_in_state += dt

        # 1. Turn this frame's keys into a command, apply it locally, and send
        #    the newest few commands to the server over UDP.
        input_x, input_y = read_movement_input()
        game.prediction.make_command(input_x, input_y, dt)
        packet = protocol.pack_commands(game.udp_token, game.prediction.commands_to_send())
        game.net.send_udp(packet)

        # 2. Draw our own player at the predicted position. (Other players'
        #    draw positions are set straight from each snapshot in Game.)
        me = game.my_player()
        if me is not None and game.prediction.ready:
            me.draw_x = game.prediction.x
            me.draw_y = game.prediction.y

    def render(self):
        game = self.game
        clear_background(BACKGROUND_COLOR)

        self._draw_players()
        self._draw_hud()

        if not game.prediction.ready and self.time_in_state > NO_DATA_WARNING_SECONDS:
            draw_text_centered("Waiting for game data from the server (is UDP blocked by a firewall?)",
                               game.screen_width / 2, game.screen_height / 2, 24, TEXT_COLOR)

        if game.disconnect_reason:
            draw_disconnected_overlay(game.disconnect_reason, game.screen_width, game.screen_height)

    def _draw_players(self):
        game = self.game
        size = game.settings["player"]["size"]
        shapes = {character["id"]: character["shape"] for character in game.characters}

        others = []
        me = None
        for player in game.players.values():
            if player.character is None or player.draw_x is None:
                continue  # not in the game yet
            if player.id == game.my_id:
                me = player
            else:
                others.append(player)

        # Draw ourselves last so we are always on top.
        if me is not None:
            others.append(me)

        for player in others:
            draw_character(shapes.get(player.character, "square"),
                           player.draw_x, player.draw_y, size, player.team)

            label = "YOU" if player.id == game.my_id else f"P{player.id}"
            if player.is_host:
                label += " (HOST)"
            draw_text_centered(label, player.draw_x + size / 2, player.draw_y - 22, 16, TEXT_COLOR)

    def _draw_hud(self):
        game = self.game
        draw_text(f"TEAM {game.my_team.upper()}", 20, 20, 28, TEAM_COLORS[game.my_team])
        draw_text(f"Players online: {len(game.players)}", 20, 56, 20, TEXT_COLOR)
        draw_text_centered("WASD or arrow keys to move", game.screen_width / 2,
                           game.screen_height - 36, 20, MUTED_TEXT_COLOR)
