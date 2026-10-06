"""A minimal game state machine.

Each screen of the game (character select, playing, ...) is a GameState.
The StateMachine holds exactly one current state and forwards update/render
calls to it, so only one screen's logic runs at a time.
"""


class GameState:
    """Base class for a screen of the game. Subclasses override what they need."""

    def __init__(self, game):
        self.game = game

    def enter(self):
        """Called once when this state becomes the current state."""

    def exit(self):
        """Called once when the game switches away from this state."""

    def update(self, dt):
        """Game logic for one frame. dt is the frame time in seconds."""

    def render(self):
        """Draw this state. Called between begin_drawing() and end_drawing()."""


class StateMachine:
    def __init__(self):
        self.current = None

    def change(self, new_state):
        """Leave the current state (if any) and enter new_state."""
        if self.current is not None:
            self.current.exit()
        self.current = new_state
        self.current.enter()

    def update(self, dt):
        if self.current is not None:
            self.current.update(dt)

    def render(self):
        if self.current is not None:
            self.current.render()
