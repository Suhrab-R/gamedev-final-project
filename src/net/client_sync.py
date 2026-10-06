"""Client-side prediction: making your own player respond instantly.

Instead of waiting a round trip for the server before your player moves,
the client moves it straight away and quietly corrects to the server.
Other players are simply drawn at the newest position the server sent
(see Game._apply_snapshot).
"""

from entities.player import step_movement
from net.protocol import COMMANDS_PER_PACKET, MAX_COMMAND_DT

# Stop remembering unconfirmed commands past this many (only happens if the
# server stops answering, e.g. UDP is blocked).
MAX_PENDING_COMMANDS = 120


class LocalPrediction:
    """Predicts our own player's position.

    Every frame the held keys become a numbered command. The command is
    applied here straight away (so the controls feel instant) and sent to
    the server, which applies the same commands with the same movement code.
    Each snapshot says the last command number the server applied. We then
    start from the server's position and re-apply only the commands it hasn't
    seen yet. That lands on the same spot unless something was lost, in which
    case the server's version wins.
    """

    def __init__(self, settings):
        self.settings = settings
        self.x = 0.0
        self.y = 0.0
        self.ready = False  # True once a snapshot has told us where we are
        self.next_seq = 1
        self.pending = []  # commands sent but not yet confirmed: (seq, x, y, dt)

    def make_command(self, input_x, input_y, dt):
        """Turn this frame's input into a command and apply it locally."""
        dt = min(dt, MAX_COMMAND_DT)  # same limit the server uses
        command = (self.next_seq, input_x, input_y, dt)
        self.next_seq += 1

        self.pending.append(command)
        if len(self.pending) > MAX_PENDING_COMMANDS:
            self.pending.pop(0)

        if self.ready:
            self.x, self.y = step_movement(self.x, self.y, input_x, input_y, dt, self.settings)
        return command

    def commands_to_send(self):
        """The newest few commands. Repeating them covers lost packets."""
        return self.pending[-COMMANDS_PER_PACKET:]

    def reconcile(self, server_x, server_y, last_applied_seq):
        """Correct our prediction using a snapshot from the server."""
        # The server has applied these commands, so forget them.
        self.pending = [command for command in self.pending if command[0] > last_applied_seq]

        # Start from where the server says we are and replay the rest.
        x, y = server_x, server_y
        for _, input_x, input_y, dt in self.pending:
            x, y = step_movement(x, y, input_x, input_y, dt, self.settings)
        self.x, self.y = x, y
        self.ready = True

