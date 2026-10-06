"""The client application.

Game owns the window, the connection to the server, the client's copy of
the players, and the state machine that decides which screen is active.
"""

from pyray import *

from core.state_machine import StateMachine
from entities.player import Player
from net import protocol
from net.client import NetworkClient
from net.client_sync import LocalPrediction
from states.character_select import CharacterSelectState

WINDOW_TITLE = "Final Project"


class Game:
    def __init__(self, settings, characters, server_address, port):
        self.settings = settings
        self.characters = characters
        self.server_address = server_address
        self.screen_width = settings["world"]["width"]
        self.screen_height = settings["world"]["height"]

        self.net = NetworkClient(server_address, port)
        self.my_id = None  # set when the server's welcome message arrives
        self.my_team = None
        self.udp_token = None  # goes in every UDP packet we send
        self.players = {}  # player id -> Player, built from the server's roster
        self.disconnect_reason = None

        # Our own player is predicted so it moves instantly; everyone else is
        # drawn at the newest position the server sent.
        self.prediction = LocalPrediction(settings)
        self.latest_snapshot_tick = -1  # tick of the newest snapshot applied

        self.states = StateMachine()

    def my_player(self):
        """This client's own Player, or None until the server has sent it."""
        return self.players.get(self.my_id)

    def run(self):
        init_window(self.screen_width, self.screen_height, WINDOW_TITLE)
        set_target_fps(self.settings["client"]["fps"])
        self.states.change(CharacterSelectState(self))

        # Main loop: read the network, update the current state, then draw it.
        while not window_should_close():
            dt = get_frame_time()
            self._process_network()
            self.states.update(dt)

            begin_drawing()
            self.states.render()
            end_drawing()

        self.net.close()
        close_window()

    def _process_network(self):
        # TCP messages: joining, roster changes, disconnects
        for message in self.net.poll():
            kind = message.get("type")
            if kind == protocol.WELCOME:
                self.my_id = message["id"]
                self.my_team = message["team"]
                self.udp_token = message["token"]
                self.net.set_udp_port(message["udp_port"])
            elif kind == protocol.ROSTER:
                self._apply_roster(message["players"])
            elif kind == protocol.DISCONNECTED:
                self.disconnect_reason = message["reason"]

        # UDP packets: position snapshots
        for packet in self.net.poll_udp():
            if packet[0] != protocol.PACKET_SNAPSHOT:
                continue
            unpacked = protocol.unpack_snapshot(packet)
            if unpacked is not None:
                self._apply_snapshot(*unpacked)

    def _apply_roster(self, roster):
        """Make self.players match the server's list of who is connected."""
        seen_ids = set()
        for data in roster:
            player_id = data["id"]
            seen_ids.add(player_id)
            if player_id not in self.players:
                self.players[player_id] = Player(id=player_id, team=data["team"])
            self.players[player_id].apply_roster_dict(data)

        # Remove players who have left the server.
        for player_id in list(self.players):
            if player_id not in seen_ids:
                del self.players[player_id]

    def _apply_snapshot(self, tick, snapshot_players):
        """Use the server's newest positions for everyone."""
        # UDP can deliver packets late or out of order; ignore anything older
        # than what we already have.
        if tick <= self.latest_snapshot_tick:
            return
        self.latest_snapshot_tick = tick

        for player_id, x, y, last_command_seq in snapshot_players:
            if player_id == self.my_id:
                # Our own player: correct the prediction (PlayingState draws it).
                self.prediction.reconcile(x, y, last_command_seq)
                continue
            player = self.players.get(player_id)
            if player is None:
                continue  # their roster entry (TCP) hasn't arrived yet
            # Everyone else: draw them exactly where the server says they are.
            player.x = player.draw_x = x
            player.y = player.draw_y = y
