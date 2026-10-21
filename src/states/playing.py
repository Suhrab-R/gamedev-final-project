"""State 2: in the game, running and jumping with the other players.

Each frame the held keys go to the host (straight into the server on the
host's own computer, over UDP from a client). Every player is drawn where
the host says they are: on the host that is the server's own data, on a
client it is the newest snapshot.
"""

from pyray import *

from core.state_machine import GameState
from ui.draw import (
    BACKGROUND_COLOR, MUTED_TEXT_COLOR, TEAM_COLORS, TEXT_COLOR,
    draw_disconnected_overlay, draw_level, draw_text_centered,
)

# Show a hint if no positions have arrived after this many seconds.
NO_DATA_WARNING_SECONDS = 2.0


def read_axis(negative_key, positive_key, last_pressed):
    """Return (value, last_pressed) for one axis made of two opposite keys.

    value is -1, 0 or 1. If both keys are held, the one pressed most recently
    wins (instead of them cancelling out to 0), so holding D and then also
    pressing A turns you around. last_pressed (-1 or 1) remembers which key
    went down last; pass back the returned one next frame.
    """
    if is_key_pressed(negative_key):
        last_pressed = -1
    if is_key_pressed(positive_key):
        last_pressed = 1

    negative_held = is_key_down(negative_key)
    positive_held = is_key_down(positive_key)
    if negative_held and positive_held:
        return last_pressed, last_pressed
    if negative_held:
        return -1, last_pressed
    if positive_held:
        return 1, last_pressed
    return 0, last_pressed


class PlayingState(GameState):
    def enter(self):
        self.time_in_state = 0.0
        # Which key of each direction pair (A/D, W/S) was pressed most recently.
        self.last_pressed_x = 1
        self.last_pressed_y = 1
        # player id -> the jump_count we last played a jump sound for.
        self.heard_jump_counts = {}

    def update(self, dt):
        self.time_in_state += dt
        # Send this frame's keys. The host moves us; we just draw the result.
        self.game.session.send_input(*self._read_input())
        self._play_jump_sounds()

    def _play_jump_sounds(self):
        """Play the jump sound for every player whose jump count changed.

        Jumps happen on the host, so a client can't see them directly; the
        host counts each player's jumps and sends the count in snapshots.
        If a snapshot is lost the next one still has the new count, so the
        sound isn't lost with it.
        """
        for player in self.game.session.players.values():
            if player.character is None:
                continue
            heard = self.heard_jump_counts.get(player.id)
            if heard is not None and heard != player.jump_count:
                self.game.assets.play("jump")
            # First time we see a player, just remember their count (no sound).
            self.heard_jump_counts[player.id] = player.jump_count

    def _read_input(self):
        """Return (input_x, input_y, jump_held, run_held) for the keys held right now.

        WASD gives the direction (-1, 0 or 1 on each axis), SPACE is jump and
        either SHIFT is run.
        """
        input_x, self.last_pressed_x = read_axis(KeyboardKey.KEY_A, KeyboardKey.KEY_D, self.last_pressed_x)
        input_y, self.last_pressed_y = read_axis(KeyboardKey.KEY_W, KeyboardKey.KEY_S, self.last_pressed_y)
        jump_held = is_key_down(KeyboardKey.KEY_SPACE)
        run_held = is_key_down(KeyboardKey.KEY_LEFT_SHIFT) or is_key_down(KeyboardKey.KEY_RIGHT_SHIFT)
        return input_x, input_y, jump_held, run_held

    def render(self):
        game = self.game
        session = game.session
        clear_background(BACKGROUND_COLOR)

        draw_level(game.settings["world"])
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
        width = game.settings["player"]["width"]
        height = game.settings["player"]["height"]

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
            game.draw_player_character(player.character, player.x, player.y,
                                       width, height, player.team, player.facing)

            label = "YOU" if player.id == my_id else f"P{player.id}"
            if player.is_host:
                label += " (HOST)"
            # Team-colored, since sprite characters look the same on both teams.
            draw_text_centered(label, player.x + width / 2, player.y - 22, 16, TEAM_COLORS[player.team])

    def _draw_hud(self):
        game = self.game
        session = game.session
        draw_text(f"TEAM {session.my_team.upper()}", 20, 20, 28, TEAM_COLORS[session.my_team])
        draw_text(f"Players online: {len(session.players)}", 20, 56, 20, TEXT_COLOR)
        me = game.my_player()
        if me is not None and me.is_host:
            draw_text(f"Hosting on {session.lan_ip}", 20, 84, 20, MUTED_TEXT_COLOR)
        draw_text_centered("A / D to move,  SHIFT to run,  SPACE to jump (hold for higher)",
                           game.screen_width / 2, 20, 20, MUTED_TEXT_COLOR)
