"""The two ways this computer can be in a game: hosting it or joining it.

Game and the states talk to either kind of session through the same small
set of methods, so they work the same whether this computer is the host or a
client:

    update(dt)                       networking (and, for the host, the server) for one frame
    send_input(input_x, input_y)     the movement keys held this frame
    choose_character(character_id)
    close()

and read the same attributes:

    players            player id -> Player
    my_id, my_team     None until this computer has a player
    disconnect_reason  None while everything is fine
    address            the "ip:port" shown on screen
    has_positions      True once player positions are coming in
"""

from entities.player import Player
from net import protocol
from net.client import NetworkClient
from net.game_server import GameServer, get_lan_ip


class HostSession:
    """This computer runs the server inside the game, and plays on it."""

    def __init__(self, settings, characters, port):
        self.server = GameServer(settings, characters, port)
        self.lan_ip = get_lan_ip()  # shown on screen so others know what to join
        self.address = f"{self.lan_ip}:{port}"
        # The host draws the server's real players directly, no network in between.
        self.players = self.server.players
        self.my_id = None
        self.my_team = None
        self.disconnect_reason = None
        self.has_positions = True

        try:
            self.server.start()
        except OSError:
            self.disconnect_reason = f"Can't host: port {port} is already in use. Is a game already hosting here?"
            return
        me = self.server.add_local_player()
        self.my_id = me.id
        self.my_team = me.team

    def update(self, dt):
        if self.disconnect_reason is None:
            self.server.step(dt)

    def send_input(self, input_x, input_y):
        self.server.set_input(self.my_id, input_x, input_y)

    def choose_character(self, character_id):
        self.server.choose_character(self.my_id, character_id)

    def close(self):
        self.server.stop()


class ClientSession:
    """This computer joins a host over the network and draws what the host sends."""

    def __init__(self, server_address, port):
        self.net = NetworkClient(server_address, port)
        self.address = f"{server_address}:{port}"
        self.players = {}  # built from the host's roster and snapshots
        self.my_id = None  # set when the host's welcome message arrives
        self.my_team = None
        self.disconnect_reason = None
        self.has_positions = False  # becomes True with the first snapshot

        self._udp_token = None  # goes in every UDP packet we send
        self._input_seq = 0  # numbers our input packets so the host can ignore late ones
        self._latest_frame = -1  # frame number of the newest snapshot applied

    def update(self, dt):
        # TCP messages: joining, roster changes, disconnects
        for message in self.net.poll():
            kind = message.get("type")
            if kind == protocol.WELCOME:
                self.my_id = message["id"]
                self.my_team = message["team"]
                self._udp_token = message["token"]
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

    def send_input(self, input_x, input_y):
        """Send the held keys to the host. Called every frame while playing."""
        if self._udp_token is None:
            return
        self._input_seq += 1
        self.net.send_udp(protocol.pack_input(self._udp_token, self._input_seq, input_x, input_y))

    def choose_character(self, character_id):
        self.net.send({"type": protocol.CHOOSE_CHARACTER, "character": character_id})

    def close(self):
        self.net.close()

    def _apply_roster(self, roster):
        """Make self.players match the host's list of who is connected."""
        seen_ids = set()
        for data in roster:
            player_id = data["id"]
            seen_ids.add(player_id)
            player = self.players.get(player_id)
            if player is None:
                player = Player(id=player_id, team=data["team"])
                self.players[player_id] = player
                just_spawned = True
            else:
                just_spawned = player.character is None and data["character"] is not None

            player.apply_roster_dict(data)
            # Use the roster's position only when a player first appears, so they
            # show up at their spawn point. After that, snapshots move them.
            if just_spawned:
                player.x = data["x"]
                player.y = data["y"]

        # Remove players who have left.
        for player_id in list(self.players):
            if player_id not in seen_ids:
                del self.players[player_id]

    def _apply_snapshot(self, frame, snapshot_players):
        """Put every player exactly where the host says they are."""
        # UDP can deliver packets late or out of order; ignore anything older
        # than what we already have.
        if frame <= self._latest_frame:
            return
        self._latest_frame = frame
        self.has_positions = True

        for player_id, x, y in snapshot_players:
            player = self.players.get(player_id)
            if player is not None:
                player.x = x
                player.y = y
