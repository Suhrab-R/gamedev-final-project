"""The two ways this computer can be in a game: hosting it or joining it.

Game and the states talk to either kind of session through the same small
set of methods, so they work the same whether this computer is the host or a
client:

    update(dt)                       networking (and, for the host, the server) for one frame
    send_input(input_x, input_y, jump_held, run_held)   the keys held this frame
    choose_character(character_id)
    close()

and read the same attributes:

    players            player id -> Player
    enemies            enemy id -> Enemy
    level              platforms, enemies and flag (core/level.py)
    completed_by_id    id of the player who reached the flag, or None
    completed_team     that player's team
    complete_time_left seconds until everyone goes back to the start
    camera_y           team -> world y at the top of that team's screen
    scroll_x           how far a runner level's course has scrolled past the screen
    my_id, my_team     None until this computer has a player
    disconnect_reason  None while everything is fine
    address            the "ip:port" shown on screen
    has_positions      True once player positions are coming in
"""

from core.level import ENEMY_KINDS, clean_level, load_level
from entities.enemy import STATES, Enemy
from entities.player import TEAM_BLUE, TEAM_RED, TEAMS, Player
from net import protocol
from net.client import NetworkClient
from net.game_server import GameServer, get_lan_ip


class HostSession:
    """This computer runs the server inside the game, and plays on it."""

    def __init__(self, settings, characters, level_file, port):
        self.level_file = level_file  # e.g. "level2.json"; the level editor saves to it
        self.server = GameServer(settings, characters, load_level(level_file), port)
        self.lan_ip = get_lan_ip()  # shown on screen so others know what to join
        self.address = f"{self.lan_ip}:{port}"
        # The host draws the server's real players directly, no network in between.
        self.players = self.server.players
        self.enemies = self.server.enemies
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

    @property
    def level(self):
        return self.server.level

    @property
    def completed_by_id(self):
        return self.server.completed_by.id if self.server.completed_by is not None else None

    @property
    def completed_team(self):
        return self.server.completed_by.team if self.server.completed_by is not None else None

    @property
    def complete_time_left(self):
        return self.server.complete_time_left

    @property
    def camera_y(self):
        return self.server.camera_y

    @property
    def scroll_x(self):
        return self.server.scroll_x

    # The level editor's tools (only the host has the editor).

    def set_level(self, level):
        """Swap in a new level for everyone."""
        self.server.set_level(level)

    def place_my_player(self, x, y):
        self.server.place_player(self.my_id, x, y)

    def is_flying(self):
        return self.server.players[self.my_id].flying

    def set_flying(self, flying):
        self.server.set_flying(self.my_id, flying)

    def set_scroll_paused(self, paused):
        self.server.scroll_paused = paused

    def set_scroll(self, x):
        self.server.set_scroll(x)

    def update(self, dt):
        if self.disconnect_reason is None:
            self.server.step(dt)

    def send_input(self, input_x, input_y, jump_held, run_held):
        self.server.set_input(self.my_id, input_x, input_y, jump_held, run_held)

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
        self.enemies = {}  # built from snapshots
        self.my_id = None  # set when the host's welcome message arrives
        self.my_team = None
        self.disconnect_reason = None
        self.has_positions = False  # becomes True with the first snapshot
        # Empty until the host sends its level (right after the welcome).
        self.level = clean_level({})
        self.completed_by_id = None
        self.completed_team = None
        self.complete_time_left = 0.0
        self.camera_y = {team: 0.0 for team in TEAMS}
        self.scroll_x = 0.0

        self._udp_token = None  # goes in every UDP packet we send
        self._input_seq = 0  # numbers our input packets so the host can ignore late ones
        self._latest_frame = -1  # frame number of the newest snapshot applied

    def update(self, dt):
        self.complete_time_left = max(0.0, self.complete_time_left - dt)
        if self.complete_time_left == 0:
            self.completed_by_id = None

        # TCP messages: joining, roster changes, the level, disconnects
        for message in self.net.poll():
            kind = message.get("type")
            if kind == protocol.WELCOME:
                self.my_id = message["id"]
                self.my_team = message["team"]
                self._udp_token = message["token"]
                self.net.set_udp_port(message["udp_port"])
            elif kind == protocol.ROSTER:
                self._apply_roster(message["players"])
            elif kind == protocol.LEVEL:
                self.level = clean_level(message["level"])
            elif kind == protocol.LEVEL_COMPLETE:
                self.completed_by_id = message["player"]
                self.completed_team = message["team"]
                self.complete_time_left = message["seconds"]
            elif kind == protocol.DISCONNECTED:
                self.disconnect_reason = message["reason"]

        # UDP packets: position snapshots
        for packet in self.net.poll_udp():
            if packet[0] != protocol.PACKET_SNAPSHOT:
                continue
            unpacked = protocol.unpack_snapshot(packet)
            if unpacked is not None:
                self._apply_snapshot(*unpacked)

    def send_input(self, input_x, input_y, jump_held, run_held):
        """Send the held keys to the host. Called every frame while playing."""
        if self._udp_token is None:
            return
        self._input_seq += 1
        self.net.send_udp(protocol.pack_input(self._udp_token, self._input_seq,
                                              input_x, input_y, jump_held, run_held))

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

    def _apply_snapshot(self, frame, cameras, snapshot_players, snapshot_enemies):
        """Put the cameras, every player and every enemy exactly where the host says they are."""
        # UDP can deliver packets late or out of order; ignore anything older
        # than what we already have.
        if frame <= self._latest_frame:
            return
        self._latest_frame = frame
        self.has_positions = True
        self.scroll_x, self.camera_y[TEAM_BLUE], self.camera_y[TEAM_RED] = cameras

        for player_id, x, y, facing, jump_count, vx, on_ground, invulnerable, lives in snapshot_players:
            player = self.players.get(player_id)
            if player is not None:
                player.x = x
                player.y = y
                player.facing = facing
                player.jump_count = jump_count
                player.vx = vx
                player.on_ground = on_ground
                player.invulnerable = invulnerable
                player.lives = lives

        # Enemies only really exist on the host; here we just mirror the snapshot.
        seen_ids = set()
        for enemy_id, x, y, state_index, kind_index in snapshot_enemies:
            seen_ids.add(enemy_id)
            enemy = self.enemies.get(enemy_id)
            if enemy is None:
                enemy = Enemy(id=enemy_id, platform=None)
                self.enemies[enemy_id] = enemy
            enemy.x = x
            enemy.y = y
            enemy.state = STATES[state_index]
            enemy.kind = ENEMY_KINDS[kind_index]
        for enemy_id in list(self.enemies):
            if enemy_id not in seen_ids:
                del self.enemies[enemy_id]
