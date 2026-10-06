"""Keeping the client's picture of the game smooth and responsive.

Two standard multiplayer techniques:

- LocalPrediction (your own player): move instantly on this computer instead
  of waiting a round trip for the server, then quietly correct to the server.
- SnapshotInterpolator (everyone else): draw other players slightly in the
  past, blending between two real snapshots, so they glide instead of jumping
  each time a snapshot arrives.
"""

from collections import deque

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


class SnapshotInterpolator:
    """Works out where to draw other players each frame.

    Snapshots arrive about 30 times a second, and unevenly over Wi-Fi, while
    we draw 60 frames a second. So other players are drawn `delay` seconds
    behind the newest snapshot, at a point between two snapshots we already
    have, blending between them. Time is measured in server ticks (each
    snapshot is stamped with the tick it was taken on).
    """

    def __init__(self, tick_rate, delay_seconds):
        self.tick_rate = tick_rate
        self.delay_ticks = delay_seconds * tick_rate
        self.snapshots = deque()  # (tick, {player_id: (x, y)}), oldest first
        self.render_tick = None  # the moment in server time we are drawing

    def add(self, tick, positions):
        """Store a snapshot. Returns False if it is older than one we already have."""
        if self.snapshots and tick <= self.snapshots[-1][0]:
            return False  # UDP can deliver packets late or out of order
        self.snapshots.append((tick, positions))
        return True

    def advance(self, dt):
        """Move the drawing clock forward by one frame."""
        if not self.snapshots:
            return
        target = self.snapshots[-1][0] - self.delay_ticks

        if self.render_tick is None or abs(target - self.render_tick) > self.tick_rate / 2:
            # First snapshot, or way off (e.g. after a long freeze): jump straight there.
            self.render_tick = target
        else:
            # Advance at normal speed, and drift gently toward the target so
            # we neither run out of snapshots nor fall further behind.
            self.render_tick += dt * self.tick_rate
            self.render_tick += (target - self.render_tick) * min(1.0, dt * 2.0)

        # Throw away snapshots that are no longer needed: keep only one that
        # is older than the moment we are drawing.
        while len(self.snapshots) >= 2 and self.snapshots[1][0] <= self.render_tick:
            self.snapshots.popleft()

    def position_of(self, player_id):
        """Where to draw a player right now, or None if they aren't in any snapshot."""
        before = None  # newest snapshot at or before render_tick containing this player
        for tick, positions in self.snapshots:
            if player_id not in positions:
                continue
            if tick <= self.render_tick:
                before = (tick, positions[player_id])
                continue

            # This snapshot is after render_tick: blend between `before` and it.
            if before is None:
                return positions[player_id]
            before_tick, (before_x, before_y) = before
            after_x, after_y = positions[player_id]
            t = (self.render_tick - before_tick) / (tick - before_tick)  # 0..1
            return (before_x + (after_x - before_x) * t,
                    before_y + (after_y - before_y) * t)

        # No newer snapshot (e.g. a gap in packets): hold the latest position.
        return before[1] if before is not None else None
