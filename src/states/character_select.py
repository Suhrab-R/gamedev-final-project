"""State 1: connect to the server and pick a character.

The server has already put the player on a team, so the characters are
shown in that team's color. After the player confirms, the choice is sent
to the server, and the game moves to PlayingState only once the server's
roster shows the character was accepted.
"""

from pyray import *

from core.state_machine import GameState
from net import protocol
from states.playing import PlayingState
from ui.draw import (
    BACKGROUND_COLOR, MUTED_TEXT_COLOR, TEAM_COLORS, TEXT_COLOR,
    draw_character, draw_disconnected_overlay, draw_text_centered,
)

# Layout of the character cards
CARD_WIDTH = 220
CARD_HEIGHT = 260
CARD_GAP = 40
CARD_TOP = 230
PREVIEW_SIZE = 110  # the shape is drawn bigger here than in game


class CharacterSelectState(GameState):
    def enter(self):
        self.selected = 0
        self.confirmed = False  # True once the choice is sent to the server

    def update(self, dt):
        game = self.game
        me = game.my_player()

        # The server accepted the choice: go into the game.
        if me is not None and me.character is not None:
            game.states.change(PlayingState(game))
            return

        # Nothing to do while connecting, after confirming, or if disconnected.
        if game.my_id is None or self.confirmed or game.disconnect_reason:
            return

        count = len(game.characters)
        if is_key_pressed(KeyboardKey.KEY_LEFT) or is_key_pressed(KeyboardKey.KEY_A):
            self.selected = (self.selected - 1) % count
        if is_key_pressed(KeyboardKey.KEY_RIGHT) or is_key_pressed(KeyboardKey.KEY_D):
            self.selected = (self.selected + 1) % count
        if is_key_pressed(KeyboardKey.KEY_ENTER) or is_key_pressed(KeyboardKey.KEY_SPACE):
            character_id = game.characters[self.selected]["id"]
            game.net.send({"type": protocol.CHOOSE_CHARACTER, "character": character_id})
            self.confirmed = True

    def render(self):
        game = self.game
        width, height = game.screen_width, game.screen_height
        clear_background(BACKGROUND_COLOR)

        if game.my_id is None:
            # Still waiting for the server's welcome message.
            if game.disconnect_reason:
                draw_disconnected_overlay(game.disconnect_reason, width, height)
            else:
                draw_text_centered(f"Connecting to server at {game.server_address}...",
                                   width / 2, height / 2 - 15, 30, TEXT_COLOR)
            return

        team = game.my_team
        team_color = TEAM_COLORS[team]

        # Header: title, team banner and host notice
        draw_text_centered("CHOOSE YOUR CHARACTER", width / 2, 60, 40, TEXT_COLOR)
        draw_text_centered(f"You are on TEAM {team.upper()}", width / 2, 120, 30, team_color)
        me = game.my_player()
        if me is not None and me.is_host:
            draw_text_centered("You are the host", width / 2, 160, 20, MUTED_TEXT_COLOR)

        self._draw_cards(team, width)

        # Footer: controls, or a waiting message after confirming
        if self.confirmed:
            footer = "Waiting for the server..."
        else:
            footer = "A / D or LEFT / RIGHT to choose,  ENTER or SPACE to confirm"
        draw_text_centered(footer, width / 2, CARD_TOP + CARD_HEIGHT + 60, 22, TEXT_COLOR)

        if game.disconnect_reason:
            draw_disconnected_overlay(game.disconnect_reason, width, height)

    def _draw_cards(self, team, screen_width):
        characters = self.game.characters
        total_width = len(characters) * CARD_WIDTH + (len(characters) - 1) * CARD_GAP
        left = (screen_width - total_width) / 2

        for index, character in enumerate(characters):
            card_x = left + index * (CARD_WIDTH + CARD_GAP)
            is_selected = index == self.selected
            card = Rectangle(card_x, CARD_TOP, CARD_WIDTH, CARD_HEIGHT)

            draw_rectangle_rec(card, RAYWHITE)
            if is_selected:
                draw_rectangle_lines_ex(card, 6, TEAM_COLORS[team])
            else:
                draw_rectangle_lines_ex(card, 2, LIGHTGRAY)

            preview_x = card_x + (CARD_WIDTH - PREVIEW_SIZE) / 2
            preview_y = CARD_TOP + 50
            draw_character(character["shape"], preview_x, preview_y, PREVIEW_SIZE, team)

            name_color = TEXT_COLOR if is_selected else MUTED_TEXT_COLOR
            draw_text_centered(character["name"], card_x + CARD_WIDTH / 2,
                               CARD_TOP + CARD_HEIGHT - 60, 26, name_color)
