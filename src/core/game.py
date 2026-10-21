"""The game application.

Game owns the window, the session (hosting or joining, see net/session.py)
and the state machine that decides which screen is active.
"""

from pyray import *

from core.assets import Assets
from core.settings import reload_settings
from core.state_machine import StateMachine
from states.character_select import CharacterSelectState
from ui.draw import draw_character, draw_notice

WINDOW_TITLE = "Final Project"
NOTICE_SECONDS = 2.5  # how long the "settings reloaded" message stays up


class Game:
    def __init__(self, settings, characters, session):
        self.settings = settings
        self.characters = characters
        self.session = session
        # The window size is fixed once it opens, so editing world width/height
        # needs a restart (reloading settings won't resize the window).
        self.screen_width = settings["world"]["width"]
        self.screen_height = settings["world"]["height"]
        self.states = StateMachine()
        self.assets = None  # loaded in run(), once the window exists

        # A short message shown at the bottom of the screen (e.g. after F5).
        self.notice = ""
        self.notice_time_left = 0.0

    def draw_player_character(self, character_id, x, y, width, height, team, facing=1, sprite_scale=None):
        """Draw a character (sprite or placeholder rectangle) in the box at (x, y)."""
        if sprite_scale is None:
            sprite_scale = self.settings["player"]["sprite_scale"]
        texture = self.assets.character_texture(character_id, team)
        draw_character(texture, x, y, width, height, team, facing, sprite_scale)

    def my_player(self):
        """This computer's own Player, or None until it has one."""
        return self.session.players.get(self.session.my_id)

    def run(self):
        init_window(self.screen_width, self.screen_height, WINDOW_TITLE)
        set_target_fps(self.settings["client"]["fps"])
        init_audio_device()
        set_master_volume(self.settings["audio"]["master_volume"])
        # Load every texture and sound once, now that the window and audio
        # device exist (see core/assets.py).
        self.assets = Assets(self.characters)
        self.states.change(CharacterSelectState(self))

        # Main loop. Update first (the current state reads this frame's keys and
        # sends them, then the session runs the network and, on the host, the
        # server), then draw the result.
        while not window_should_close():
            dt = get_frame_time()
            self._check_settings_reload(dt)
            self.states.update(dt)
            self.session.update(dt)

            begin_drawing()
            self.states.render()
            if self.notice_time_left > 0:
                draw_notice(self.notice, self.screen_width, self.screen_height)
            end_drawing()

        self.session.close()
        self.assets.unload()
        close_audio_device()
        close_window()

    def _check_settings_reload(self, dt):
        """F5 re-reads data/settings.json, for tuning without restarting.

        Physics runs on the host, so press F5 in the host's window to change
        speeds and jumps for everyone. A client's own file only changes how
        that client draws things.
        """
        self.notice_time_left -= dt
        if not is_key_pressed(KeyboardKey.KEY_F5):
            return
        error = reload_settings(self.settings)
        set_master_volume(self.settings["audio"]["master_volume"])
        self.notice = error or "Reloaded data/settings.json"
        self.notice_time_left = NOTICE_SECONDS
