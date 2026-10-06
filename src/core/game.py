"""The game application.

Game owns the window, the session (hosting or joining, see net/session.py)
and the state machine that decides which screen is active.
"""

from pyray import *

from core.state_machine import StateMachine
from states.character_select import CharacterSelectState

WINDOW_TITLE = "Final Project"


class Game:
    def __init__(self, settings, characters, session):
        self.settings = settings
        self.characters = characters
        self.session = session
        self.screen_width = settings["world"]["width"]
        self.screen_height = settings["world"]["height"]
        self.states = StateMachine()

    def my_player(self):
        """This computer's own Player, or None until it has one."""
        return self.session.players.get(self.session.my_id)

    def run(self):
        init_window(self.screen_width, self.screen_height, WINDOW_TITLE)
        set_target_fps(self.settings["client"]["fps"])
        self.states.change(CharacterSelectState(self))

        # Main loop. Update first (the current state reads this frame's keys and
        # sends them, then the session runs the network and, on the host, the
        # server), then draw the result.
        while not window_should_close():
            dt = get_frame_time()
            self.states.update(dt)
            self.session.update(dt)

            begin_drawing()
            self.states.render()
            end_drawing()

        self.session.close()
        close_window()
