"""The dedicated game server.

The server is the single source of truth for the game. Clients send numbered
movement commands (their held keys for each frame) over UDP; the server
applies them with the shared movement code and sends a snapshot of every
player's position back over UDP. Who is on which team, which character they
picked and who is host is sent over TCP as a "roster" whenever it changes.

Rules handled here:
- The first client to connect is the host. If the host leaves, the next
  oldest connection becomes host.
- Teams stay balanced: a new player joins the smaller team. When the teams
  are even, the first player gets a random team and after that teams
  alternate (blue, red, blue, ... or red, blue, red, ...).
"""

import math
import queue
import random
import socket
import threading
import time

from entities.player import TEAM_BLUE, TEAM_RED, TEAMS, Player, other_team, step_movement
from net import protocol
from net.server_connection import ClientConnection


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
        self.tick_rate = settings["network"]["tick_rate"]
        # Simulate every tick, but only send a snapshot every few ticks.
        self.snapshot_every = max(1, round(self.tick_rate / settings["network"]["snapshot_rate"]))
        self.valid_characters = {character["id"] for character in characters}

        # TCP messages from all client threads land here; only the main thread reads it.
        self.inbox = queue.Queue()
        self.udp = None  # UDP socket, created in serve_forever()
        self.tick = 0  # number of simulation steps so far; stamped on snapshots

        self.connections = {}  # player id -> ClientConnection
        self.players = {}  # player id -> Player
        self.join_order = []  # player ids, oldest first (index 0 is the host)
        self.player_id_by_token = {}  # UDP token -> player id

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def serve_forever(self):
        # TCP and UDP both use the same port number (they don't clash).
        listener = socket.create_server(("", self.port))
        self.udp = protocol.make_udp_socket(self.port)
        print(f"Server running. Players join with:  python src/main.py --server {get_lan_ip()}")
        print(f"(port {self.port}, TCP + UDP, press Ctrl+C to stop)")

        threading.Thread(target=self._accept_loop, args=(listener,), daemon=True).start()

        # Fixed timestep: the game advances in equal steps of dt, tick_rate
        # times per second, no matter how fast this computer is. That keeps
        # the simulation the same for everyone and makes timing predictable.
        dt = 1.0 / self.tick_rate
        next_tick = time.perf_counter()
        try:
            while True:
                self._process_inbox()
                self._receive_udp()
                self._update(dt)
                self.tick += 1
                if self.tick % self.snapshot_every == 0:
                    self._send_snapshots()

                # Sleep until it is time for the next tick.
                next_tick += dt
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.perf_counter()  # fell behind; don't try to catch up
        except KeyboardInterrupt:
            print("\nShutting down server.")
        finally:
            listener.close()
            self.udp.close()
            for connection in self.connections.values():
                connection.close()

    def _accept_loop(self, listener):
        """Background thread: accept new clients and hand them to the main thread."""
        next_id = 1
        while True:
            try:
                sock, address = listener.accept()
            except OSError:
                return  # listener was closed
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connection = ClientConnection(next_id, sock, address, self.inbox)
            next_id += 1
            # Queue the "connected" event before starting the reader thread so it
            # is always processed before any message from this client.
            self.inbox.put((connection, {"type": protocol.CONNECTED}))
            connection.start()

    def _process_inbox(self):
        """Handle every TCP message that arrived since the last tick."""
        while True:
            try:
                connection, message = self.inbox.get_nowait()
            except queue.Empty:
                return

            kind = message.get("type")
            if kind == protocol.CONNECTED:
                self._add_player(connection)
            elif kind == protocol.DISCONNECTED:
                self._remove_player(connection.id)
            elif kind == protocol.CHOOSE_CHARACTER:
                player = self.players.get(connection.id)
                if player is not None:
                    self._choose_character(player, message.get("character"))

    def _receive_udp(self):
        """Read every UDP packet waiting on the socket and queue its commands."""
        while True:
            try:
                data, address = self.udp.recvfrom(protocol.MAX_PACKET_SIZE)
            except BlockingIOError:
                return  # nothing left to read
            except OSError:
                continue  # a bad packet; skip it

            if not data or data[0] != protocol.PACKET_COMMANDS:
                continue
            unpacked = protocol.unpack_commands(data)
            if unpacked is None:
                continue
            token, commands = unpacked

            # The token tells us which player sent this packet.
            player_id = self.player_id_by_token.get(token)
            if player_id is None:
                continue
            player = self.players[player_id]
            self.connections[player_id].udp_address = address  # where to send snapshots
            if player.character is None:
                continue  # not in the game yet

            # Packets repeat the last few commands, so skip ones already queued
            # or applied. Only commands newer than the newest one we have count.
            if player.pending_commands:
                newest_seq = player.pending_commands[-1][0]
            else:
                newest_seq = player.last_command_seq
            for command in commands:
                if command[0] > newest_seq:
                    player.pending_commands.append(command)
                    newest_seq = command[0]

    def _update(self, dt):
        """Advance the game by one tick.

        Players move by applying the commands their clients sent, each with the
        frame time it covered, exactly like the client's own prediction does.
        dt is the fixed tick length, for world logic (enemies, platforms) later.
        """
        for player in self.players.values():
            for seq, input_x, input_y, command_dt in player.pending_commands:
                player.x, player.y = step_movement(
                    player.x, player.y,
                    clamp_axis(input_x), clamp_axis(input_y), clamp_dt(command_dt),
                    self.settings,
                )
                player.last_command_seq = seq
            player.pending_commands.clear()

    def _send_snapshots(self):
        """Send every in-game player's position to every client over UDP."""
        in_game = [
            (p.id, p.x, p.y, p.last_command_seq)
            for p in self.players.values() if p.character is not None
        ]
        packet = protocol.pack_snapshot(self.tick, in_game)
        for connection in self.connections.values():
            if connection.udp_address is None:
                continue  # this client hasn't sent a UDP packet yet
            try:
                self.udp.sendto(packet, connection.udp_address)
            except OSError:
                pass  # UDP is best effort; the next snapshot will follow soon

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
    # Players joining, leaving and choosing characters
    # ------------------------------------------------------------------

    def _add_player(self, connection):
        team = self._pick_team()
        player = Player(id=connection.id, team=team)
        self.players[player.id] = player
        self.connections[player.id] = connection
        self.join_order.append(player.id)
        self._update_host()

        # A random token identifies this player's UDP packets.
        token = random.getrandbits(32)
        while token in self.player_id_by_token:
            token = random.getrandbits(32)
        connection.udp_token = token
        self.player_id_by_token[token] = player.id

        connection.send({
            "type": protocol.WELCOME,
            "id": player.id,
            "team": team,
            "token": token,
            "udp_port": self.port,
        })
        self._broadcast_roster()
        role = "host" if player.is_host else "player"
        print(f"Player {player.id} joined from {connection.address[0]} as {role}, team {team}.")

    def _remove_player(self, player_id):
        if player_id not in self.players:
            return
        connection = self.connections.pop(player_id)
        connection.close()
        self.player_id_by_token.pop(connection.udp_token, None)
        del self.players[player_id]
        self.join_order.remove(player_id)
        print(f"Player {player_id} left.")
        self._update_host()
        self._broadcast_roster()

    def _pick_team(self):
        blue_count = sum(1 for p in self.players.values() if p.team == TEAM_BLUE)
        red_count = len(self.players) - blue_count
        if blue_count < red_count:
            return TEAM_BLUE
        if red_count < blue_count:
            return TEAM_RED
        if not self.join_order:
            return random.choice(TEAMS)  # very first player: random team
        # Teams are even: put this player on the opposite team of the last joiner.
        last_player = self.players[self.join_order[-1]]
        return other_team(last_player.team)

    def _update_host(self):
        """The oldest connected player is always the host."""
        for index, player_id in enumerate(self.join_order):
            player = self.players[player_id]
            was_host = player.is_host
            player.is_host = index == 0
            if player.is_host and not was_host and len(self.join_order) > 1:
                print(f"Player {player_id} is now the host.")

    def _choose_character(self, player, character_id):
        if character_id not in self.valid_characters or player.character is not None:
            return  # unknown character, or already chosen
        player.character = character_id
        player.x, player.y = self._spawn_position(player)
        self._broadcast_roster()
        print(f"Player {player.id} chose {character_id}.")

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
    """Turn an input value from a client into -1, 0 or 1."""
    return max(-1, min(1, value))


def clamp_dt(value):
    """Keep a client's frame time between 0 and MAX_COMMAND_DT seconds."""
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(value, protocol.MAX_COMMAND_DT))
