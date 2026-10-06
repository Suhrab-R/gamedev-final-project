"""The game server, which runs inside the host's game (a "listen server").

There is no separate server program: the host's Game calls step() once per
frame. The server owns the real Player objects. Every frame it moves each
player using the keys they are holding, then sends every player's position
to every client over UDP. Who is on which team, which character they picked
and who is host is sent over TCP as a "roster" whenever it changes.

The host's own player lives here too; its keys come straight from the host's
keyboard (set_input) instead of over the network, and the host's screen draws
these Player objects directly.

Team rule: a new player joins the smaller team. When the teams are even, the
host gets a random team and after that teams alternate (blue, red, blue, ...
or red, blue, red, ...).
"""

import queue
import random
import socket
import threading

from entities.player import TEAM_BLUE, TEAM_RED, TEAMS, Player, other_team, step_movement
from net import protocol
from net.server_connection import ClientConnection

# The longest step the simulation takes in one frame (seconds). If the host's
# game hitches, players move a bit less that frame instead of teleporting.
MAX_STEP_DT = 0.1


def get_lan_ip():
    """Best guess at this computer's LAN address, for players to type in."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting a UDP socket sends nothing; it only makes the OS pick
        # the network interface it would use, which tells us our address.
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


class GameServer:
    def __init__(self, settings, characters, port):
        self.port = port
        self.settings = settings
        self.valid_characters = {character["id"] for character in characters}

        # TCP messages from all client threads land here; only the game loop reads it.
        self.inbox = queue.Queue()
        self.listener = None  # TCP socket new clients connect to
        self.udp = None  # UDP socket for inputs and snapshots
        self.frame = 0  # number of steps so far; stamped on snapshots

        self.players = {}  # player id -> Player (including the host's own player)
        self.connections = {}  # player id -> ClientConnection (remote players only)
        self.join_order = []  # player ids, oldest first
        self.player_id_by_token = {}  # UDP token -> player id
        self._next_id = 1

    # ------------------------------------------------------------------
    # Starting, stepping and stopping (called by HostSession)
    # ------------------------------------------------------------------

    def start(self):
        """Open the network sockets. Raises OSError if the port is already in use."""
        # TCP and UDP both use the same port number (they don't clash).
        self.listener = socket.create_server(("", self.port))
        try:
            self.udp = protocol.make_udp_socket(self.port)
        except OSError:
            self.listener.close()
            raise
        threading.Thread(target=self._accept_loop, daemon=True).start()
        print(f"Hosting. Players join with:  python src/main.py --server {get_lan_ip()}")

    def step(self, dt):
        """Run the server for one frame: read the network, move everyone, send positions."""
        dt = min(dt, MAX_STEP_DT)
        self._process_inbox()
        self._receive_inputs()
        self._update(dt)
        self._send_snapshots()
        self.frame += 1

    def stop(self):
        """Close everything. Clients see this as the host leaving."""
        for connection in self.connections.values():
            connection.close()
        if self.listener is not None:
            self.listener.close()
        if self.udp is not None:
            self.udp.close()

    # ------------------------------------------------------------------
    # The host's own player
    # ------------------------------------------------------------------

    def add_local_player(self):
        """Create the host's player. Returns it."""
        player = self._create_player()
        player.is_host = True
        self._broadcast_roster()
        print(f"Host is player {player.id}, team {player.team}.")
        return player

    def set_input(self, player_id, input_x, input_y):
        """Set the keys a player is holding (used for the host's own player)."""
        player = self.players.get(player_id)
        if player is not None:
            player.input_x = clamp_axis(input_x)
            player.input_y = clamp_axis(input_y)

    def choose_character(self, player_id, character_id):
        """Give a player their character and put them in the game."""
        player = self.players.get(player_id)
        if player is None or character_id not in self.valid_characters or player.character is not None:
            return  # unknown player or character, or already chosen
        player.character = character_id
        player.x, player.y = self._spawn_position(player)
        self._broadcast_roster()
        print(f"Player {player.id} chose {character_id}.")

    # ------------------------------------------------------------------
    # One frame of the server
    # ------------------------------------------------------------------

    def _accept_loop(self):
        """Background thread: accept new clients and hand them to the game loop."""
        while True:
            try:
                sock, address = self.listener.accept()
            except OSError:
                return  # listener was closed
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connection = ClientConnection(sock, address, self.inbox)
            # Queue the "connected" event before starting the reader thread so it
            # is always processed before any message from this client.
            self.inbox.put((connection, {"type": protocol.CONNECTED}))
            connection.start()

    def _process_inbox(self):
        """Handle every TCP message that arrived since the last frame."""
        while True:
            try:
                connection, message = self.inbox.get_nowait()
            except queue.Empty:
                return

            kind = message.get("type")
            if kind == protocol.CONNECTED:
                self._add_remote_player(connection)
            elif kind == protocol.DISCONNECTED:
                self._remove_remote_player(connection.id)
            elif kind == protocol.CHOOSE_CHARACTER:
                self.choose_character(connection.id, message.get("character"))

    def _receive_inputs(self):
        """Read every UDP input packet waiting and remember each player's held keys."""
        while True:
            try:
                data, address = self.udp.recvfrom(protocol.MAX_PACKET_SIZE)
            except BlockingIOError:
                return  # nothing left to read
            except OSError:
                continue  # a bad packet; skip it

            if not data or data[0] != protocol.PACKET_INPUT:
                continue
            unpacked = protocol.unpack_input(data)
            if unpacked is None:
                continue
            token, sequence, input_x, input_y = unpacked

            # The token tells us which player sent this packet.
            player_id = self.player_id_by_token.get(token)
            if player_id is None:
                continue
            self.connections[player_id].udp_address = address  # where to send snapshots

            # UDP can deliver packets out of order. Only a newer packet than the
            # last one we used can change the held keys.
            player = self.players[player_id]
            if sequence > player.last_input_seq:
                player.last_input_seq = sequence
                player.input_x = clamp_axis(input_x)
                player.input_y = clamp_axis(input_y)

    def _update(self, dt):
        """Move every player in the game by the keys they are holding."""
        for player in self.players.values():
            if player.character is None:
                continue  # still on the character select screen
            player.x, player.y = step_movement(
                player.x, player.y, player.input_x, player.input_y, dt, self.settings
            )

    def _send_snapshots(self):
        """Send every in-game player's position to every client over UDP."""
        in_game = [(p.id, p.x, p.y) for p in self.players.values() if p.character is not None]
        packet = protocol.pack_snapshot(self.frame, in_game)
        for connection in self.connections.values():
            if connection.udp_address is None:
                continue  # this client hasn't sent a UDP packet yet
            try:
                self.udp.sendto(packet, connection.udp_address)
            except OSError:
                pass  # UDP is best effort; the next snapshot follows next frame

    def _broadcast_roster(self):
        """Tell every client (over TCP) who is in the game and on which team."""
        message = {
            "type": protocol.ROSTER,
            "players": [player.to_roster_dict() for player in self.players.values()],
        }
        data = protocol.encode(message)  # encode once, send to everyone
        for connection in self.connections.values():
            connection.send_encoded(data)

    # ------------------------------------------------------------------
    # Players joining and leaving
    # ------------------------------------------------------------------

    def _create_player(self):
        """Make a new Player on the right team and add it to the game."""
        player = Player(id=self._next_id, team=self._pick_team())
        self._next_id += 1
        self.players[player.id] = player
        self.join_order.append(player.id)
        return player

    def _add_remote_player(self, connection):
        player = self._create_player()
        connection.id = player.id
        self.connections[player.id] = connection

        # A random token identifies this player's UDP packets.
        token = random.getrandbits(32)
        while token in self.player_id_by_token:
            token = random.getrandbits(32)
        connection.udp_token = token
        self.player_id_by_token[token] = player.id

        connection.send({
            "type": protocol.WELCOME,
            "id": player.id,
            "team": player.team,
            "token": token,
            "udp_port": self.port,
        })
        self._broadcast_roster()
        print(f"Player {player.id} joined from {connection.address[0]}, team {player.team}.")

    def _remove_remote_player(self, player_id):
        if player_id not in self.connections:
            return
        connection = self.connections.pop(player_id)
        connection.close()
        self.player_id_by_token.pop(connection.udp_token, None)
        del self.players[player_id]
        self.join_order.remove(player_id)
        self._broadcast_roster()
        print(f"Player {player_id} left.")

    def _pick_team(self):
        blue_count = sum(1 for p in self.players.values() if p.team == TEAM_BLUE)
        red_count = len(self.players) - blue_count
        if blue_count < red_count:
            return TEAM_BLUE
        if red_count < blue_count:
            return TEAM_RED
        if not self.join_order:
            return random.choice(TEAMS)  # the very first player (the host): random team
        # Teams are even: put this player on the opposite team of the last joiner.
        last_player = self.players[self.join_order[-1]]
        return other_team(last_player.team)

    def _spawn_position(self, player):
        """Spawn on the team's side, in a column below teammates already in the game."""
        spawn = self.settings["spawn"]
        if player.team == TEAM_BLUE:
            x = spawn["blue_x"]
        else:
            x = spawn["red_x"]

        teammates_in_game = 0
        for other in self.players.values():
            if other is not player and other.team == player.team and other.character is not None:
                teammates_in_game += 1

        # How many players fit in one column before the bottom of the world.
        usable_height = self.settings["world"]["height"] - spawn["first_y"] - self.settings["player"]["size"]
        players_per_column = int(usable_height // spawn["spacing_y"]) + 1

        # Wrap back to the top once a column is full.
        row = teammates_in_game % players_per_column
        y = spawn["first_y"] + row * spawn["spacing_y"]
        return x, y


def clamp_axis(value):
    """Turn an input value into -1, 0 or 1."""
    return max(-1, min(1, value))
