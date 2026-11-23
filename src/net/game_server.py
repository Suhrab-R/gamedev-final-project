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

The server also owns the level (core/level.py): it sends it to every client
over TCP when they join and whenever it changes (set_level), and it runs
the enemies' AI (entities/enemy.py) every frame after moving the players;
their positions, AI states and kinds go out in the same snapshots. If an
enemy touches a player, the whole game goes back to the start (every player
respawns, every enemy resets). If a player reaches the flag, everyone is
told "level complete" and the game goes back to the start a few seconds
later.

Cameras: each team has its own camera, which only moves up and down (the
level is a vertical climb). It rises to keep the team's highest player in
view and never scrolls back down, so a team that climbs ahead doesn't drag
the other team's view up with it. A player who falls below their team's
camera is put back on the last platform they stood on. The cameras' heights
go out in every snapshot; each screen draws with its own team's camera.

Runner levels (level 2) work differently: the screen stays still and the
course scrolls past it (scroll_x), so the obstacles slide in from the right,
speeding up along the course. Players walk freely between the screen's edges
and the top of the screen is a ceiling. Standing on an obstacle carries you
along with it. An obstacle can push a player past the left edge; once it has
pushed them more than halfway off, they drop back in a quarter of the way
across the screen. Enemies aren't used in runner levels.

Lives: every player starts with player.lives. Respawning (falling below the
camera, falling down a pit, being knocked off the screen) costs a life; at 0
the player is out of the level. If everyone is out, the level starts over
with full lives.

Respawning also makes a player invulnerable for player.respawn_invulnerable_seconds:
enemies can't touch them, in runner levels they pass through obstacles
(but still land on the floors), and every screen draws them blinking.
"""

import queue
import random
import socket
import threading

from core.level import (
    ENEMY_KINDS, RUNNER, all_platforms, flag_rect, platforms_in_view, rects_overlap, split_end_x,
)
from entities.enemy import STATES, Enemy, EnemyBrain
from entities.physics import step_player
from entities.player import TEAM_BLUE, TEAM_RED, TEAMS, Player, hitbox_size, other_team
from net import protocol
from net.server_connection import ClientConnection

# The longest step the simulation takes in one frame (seconds). If the host's
# game hitches, players move a bit less that frame instead of teleporting
# (or falling through the ground).
MAX_STEP_DT = 0.1

# How long the "level complete" banner shows before everyone goes back to the start.
LEVEL_COMPLETE_SECONDS = 3.0

# The camera keeps the team's highest player at least this far down from the
# top of the screen (a fraction of the screen height), so you can see what's
# above you.
CAMERA_LEAD = 0.35
# How quickly a camera catches up with where it should be: it covers this
# fraction of the remaining distance per second (more = snappier).
CAMERA_CATCH_UP = 8.0

# In a runner level, a player pushed this far off the left edge (a fraction
# of their width) is out, and comes back this far across the screen (a
# fraction of its width), dropping in from this many blocks above their floor.
RUNNER_KNOCKED_OUT = 0.5
RUNNER_RESPAWN_X = 0.25
RUNNER_RESPAWN_DROP_BLOCKS = 2


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
    def __init__(self, settings, characters, level, port):
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

        self.level = None  # platforms, enemies and flag (core/level.py); set below
        self.enemies = {}  # enemy id -> Enemy
        self.enemy_brains = []  # one EnemyBrain (AI state machine) per enemy
        # Who reached the flag (a Player) and how long until everyone goes
        # back to the start; None / 0 while the level is being played.
        self.completed_by = None
        self.complete_time_left = 0.0
        # Team -> the world y at the top of that team's screen. 0 = looking at
        # the bottom of the level; it goes negative as the camera rises.
        self.camera_y = {team: 0.0 for team in TEAMS}
        # Runner levels: how far the course has scrolled past the screen (an
        # obstacle at course x is on screen at x - scroll_x). The level
        # editor pauses the scrolling while it's open.
        self.scroll_x = 0.0
        self.scroll_paused = False
        self.set_level(level)

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

    def set_input(self, player_id, input_x, input_y, jump_held, run_held):
        """Set the keys a player is holding (used for the host's own player)."""
        player = self.players.get(player_id)
        if player is not None:
            apply_input(player, input_x, input_y, jump_held, run_held)

    def choose_character(self, player_id, character_id):
        """Give a player their character and put them in the game."""
        player = self.players.get(player_id)
        if player is None or character_id not in self.valid_characters or player.character is not None:
            return  # unknown player or character, or already chosen
        player.character = character_id
        player.lives = self.settings["player"]["lives"]
        # The next free spot on the team's side: one per teammate already in the game.
        teammates_in_game = sum(1 for other in self.players.values()
                                if other is not player and other.team == player.team
                                and other.character is not None)
        player.x, player.y = self._spawn_position(player, teammates_in_game)
        player.vx = player.vy = 0.0
        self._broadcast_roster()
        print(f"Player {player.id} chose {character_id}.")

    def set_level(self, level):
        """Use a new level: remake its enemies and send it to every client.

        Players stay where they are, so the level can be changed while
        playing (the host's level editor uses this).
        """
        self.level = level
        self.enemies.clear()
        self.enemy_brains.clear()
        self._create_enemies(level["enemies"])
        data = protocol.encode({"type": protocol.LEVEL, "level": level})
        for connection in self.connections.values():
            connection.send_encoded(data)

    def place_player(self, player_id, x, y):
        """Put a player at (x, y), standing still (the level editor's "place me").
        Their team's camera jumps there too, so they don't land below it."""
        player = self.players.get(player_id)
        if player is None:
            return
        player.x, player.y = x, y
        _stop(player)
        if self.level["mode"] != RUNNER:  # a runner level's camera never moves
            self.camera_y[player.team] = self._camera_target(player.y)

    def set_scroll(self, x):
        """Scroll a runner level's course to x (the level editor uses this)."""
        self.scroll_x = min(max(x, 0.0), self._scroll_end())

    def set_flying(self, player_id, flying):
        """Turn the level editor's fly mode on or off for one player."""
        player = self.players.get(player_id)
        if player is not None:
            player.flying = flying
            _stop(player)

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
            token, sequence, input_x, input_y, jump_held, run_held = unpacked

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
                apply_input(player, input_x, input_y, jump_held, run_held)

    def _update(self, dt):
        """Run every in-game player's physics with the keys they are holding,
        then let every enemy's AI react to where the players now are."""
        runner = self.level["mode"] == RUNNER
        ceiling_y = None
        if runner:
            scrolled = self._scroll(dt)
            ceiling_y = 0.0  # the top of the screen
            # Tell the physics how fast what each player stands on is moving
            # (see ground_vx in entities/player.py): obstacles move left, the
            # ground and the middle floor don't. (The middle floor comes after
            # the obstacles in the list.) In the air, keep the value from what
            # they jumped or walked off.
            obstacle_speed = scrolled / dt if dt > 0 else 0.0
            obstacle_count = len(self.level["platforms"])
            for player in self.players.values():
                if player.flying:
                    player.ground_vx = 0.0
                elif player.standing_on is not None and player.standing_on < obstacle_count:
                    player.ground_vx = -obstacle_speed
                elif player.on_ground:
                    player.ground_vx = 0.0
        # Each team only collides with the platforms in (or near) its own view:
        # its camera in a climb level, the one shared screen in a runner level.
        world = self.settings["world"]
        platforms_by_team = {}
        floors_only_by_team = {}
        for team in TEAMS:
            view_top = self.camera_y[team]
            platforms = platforms_in_view(self.level, world, self.scroll_x, view_top, world["width"], world["height"])
            platforms_by_team[team] = platforms
            # Runner levels: what an invulnerable player collides with, i.e.
            # only the floors (the middle floor comes after the obstacles).
            floors_only_by_team[team] = platforms
            if runner:
                obstacle_count = len(self.level["platforms"])
                floors_only_by_team[team] = [None] * obstacle_count + platforms[obstacle_count:]
        # The level can change some movement values for itself (its "physics"),
        # on top of settings.json. Rebuilt every frame so F5 still works.
        physics_settings = self.settings
        if self.level["physics"]:
            physics_settings = dict(self.settings, physics=dict(self.settings["physics"], **self.level["physics"]))
        for player in self.players.values():
            if not player.in_play:
                continue  # still on the character select screen, or out of lives
            player.invulnerable_left = max(0.0, player.invulnerable_left - dt)
            player.invulnerable = player.invulnerable_left > 0
            if player.invulnerable:
                solids = floors_only_by_team[player.team]
            else:
                solids = platforms_by_team[player.team]
            step_player(player, dt, physics_settings, solids, ceiling_y=ceiling_y, flat_floor=not runner)
            if player.standing_on is not None:
                player.last_platform = player.standing_on
                # Where along the level (runner levels: the course) they stood.
                player.last_platform_x = player.x + self.scroll_x
            elif player.on_ground:
                player.last_platform = None  # on the ground
        if runner:
            self._respawn_knocked_out_players()
        else:
            self._update_cameras(dt)
            self._respawn_players_below_camera()
        self._restart_if_everyone_is_out()
        for brain in self.enemy_brains:
            brain.update(dt)

        if self.completed_by is not None:
            # Someone reached the flag: wait for the banner, then start over.
            # (Enemies can't send anyone back during this time.)
            self.complete_time_left -= dt
            if self.complete_time_left <= 0:
                self.completed_by = None
                self._reset_to_start()
            return

        # An enemy touching any player sends everyone back to the start.
        for brain in self.enemy_brains:
            caught = brain.touching_player()
            if caught is not None:
                print(f"Player {caught.id} touched enemy {brain.enemy.id}: back to the start.")
                self._reset_to_start()
                return

        winner = self._player_at_flag()
        if winner is not None:
            print(f"Player {winner.id} reached the flag: level complete.")
            self.completed_by = winner
            self.complete_time_left = LEVEL_COMPLETE_SECONDS
            data = protocol.encode({"type": protocol.LEVEL_COMPLETE, "player": winner.id,
                                    "team": winner.team, "seconds": LEVEL_COMPLETE_SECONDS})
            for connection in self.connections.values():
                connection.send_encoded(data)

    def _scroll_end(self):
        """How far a runner level's course scrolls in total (its length)."""
        return self.level["length"]

    def _scroll(self, dt):
        """Scroll a runner level's course (move the obstacles left). It speeds
        up steadily from start_speed to end_speed over the course, and waits
        while nobody is in the game yet, while the editor is open and during
        "level complete". Returns how far it scrolled this frame."""
        in_game = any(p.in_play for p in self.players.values())
        if not in_game or self.scroll_paused or self.completed_by is not None:
            return 0.0
        scroll = self.level["scroll"]
        end = self._scroll_end()
        progress = self.scroll_x / end if end > 0 else 1.0
        speed = scroll["start_speed"] + (scroll["end_speed"] - scroll["start_speed"]) * progress
        before = self.scroll_x
        self.scroll_x = min(self.scroll_x + speed * dt, end)
        return self.scroll_x - before

    def _runner_floor_y(self, player, x):
        """The floor under screen x for this player in a runner level: blue
        runs on the middle floor (while it's still there), red on the ground."""
        world = self.settings["world"]
        if player.team == TEAM_BLUE and x + self.scroll_x < split_end_x(self.level):
            return self.level["split"]["y"]
        return world["height"] - world["ground_height"]

    def _respawn_knocked_out_players(self):
        """Runner levels: a player who fell down a pit goes back to the last
        platform they stood on. A player an obstacle has pushed more than
        halfway off the left edge of the screen drops back in a quarter of
        the way across."""
        width, height = hitbox_size(self.settings)
        world = self.settings["world"]
        for player in self.players.values():
            if not player.in_play or player.flying:
                continue
            if player.y > world["height"]:  # fallen all the way down a pit
                if self._lose_life(player):
                    self._respawn_from_pit(player)
                continue
            if player.x < -width * RUNNER_KNOCKED_OUT:
                if not self._lose_life(player):
                    continue
                player.x = world["width"] * RUNNER_RESPAWN_X
                drop = RUNNER_RESPAWN_DROP_BLOCKS * world["block_size"]
                player.y = self._runner_floor_y(player, player.x) - height - drop
                _stop(player)
                self._make_invulnerable(player)
                print(f"Player {player.id} was knocked off the screen: back in.")

    def _make_invulnerable(self, player):
        """Protect a player who just respawned for a few seconds (see the top of this file)."""
        player.invulnerable_left = self.settings["player"]["respawn_invulnerable_seconds"]
        player.invulnerable = player.invulnerable_left > 0  # 0 seconds = no protection at all

    def _lose_life(self, player):
        """Take a life from a player who is about to respawn. Returns True if
        they have lives left (so respawn them), False if they're now out."""
        player.lives = max(0, player.lives - 1)
        if player.lives > 0:
            return True
        _stop(player)
        print(f"Player {player.id} is out of lives.")
        return False

    def _restart_if_everyone_is_out(self):
        """If every player in the game has run out of lives, start the level
        over with full lives (so a test run never gets stuck)."""
        in_game = [p for p in self.players.values() if p.character is not None]
        if in_game and not any(p.in_play for p in in_game):
            print("Everyone is out of lives: starting the level over.")
            self._reset_to_start()

    def _respawn_from_pit(self, player):
        """Stand a player who fell down a pit back on the last platform they
        stood on (where they stood on it), if it's still on screen. Otherwise
        they drop back in a quarter of the way across the screen."""
        width, height = hitbox_size(self.settings)
        world = self.settings["world"]
        platforms = all_platforms(self.level, world)
        index = player.last_platform
        platform = platforms[index] if index is not None and index < len(platforms) else None
        if platform is not None:
            # Where the platform is on screen now, cut to the screen's edges.
            left = max(platform["x"] - self.scroll_x, 0.0)
            right = min(platform["x"] + platform["width"] - self.scroll_x, world["width"])
            if right - left >= width:
                player.x = min(max(player.last_platform_x - self.scroll_x, left), right - width)
                player.y = platform["y"] - height
                _stop(player)
                self._make_invulnerable(player)
                print(f"Player {player.id} fell down a pit: back on the last platform.")
                return
        player.x = world["width"] * RUNNER_RESPAWN_X
        player.y = self._runner_floor_y(player, player.x) - height - RUNNER_RESPAWN_DROP_BLOCKS * world["block_size"]
        _stop(player)
        self._make_invulnerable(player)
        print(f"Player {player.id} fell down a pit: dropped back in.")

    def _camera_target(self, player_y):
        """Where a camera showing a player at player_y should be: the player
        CAMERA_LEAD of the screen down from the top, but never below the
        bottom of the level (y 0)."""
        return min(0.0, player_y - self.settings["world"]["height"] * CAMERA_LEAD)

    def _update_cameras(self, dt):
        """Move each team's camera up to its highest player (never back down,
        except while someone on the team is flying, so fly mode can look around)."""
        for team in TEAMS:
            team_players = [p for p in self.players.values() if p.team == team and p.in_play]
            if not team_players:
                continue
            highest = min(team_players, key=lambda p: p.y)  # smaller y = higher up
            target = self._camera_target(highest.y)
            camera = self.camera_y[team]
            if target < camera or any(p.flying for p in team_players):
                # Ease toward the target instead of jumping there.
                camera += (target - camera) * min(1.0, CAMERA_CATCH_UP * dt)
            self.camera_y[team] = camera

    def _respawn_players_below_camera(self):
        """A player who has fallen out of the bottom of their team's view goes
        back to the last platform they stood on."""
        screen_height = self.settings["world"]["height"]
        for player in self.players.values():
            if not player.in_play or player.flying:
                continue
            if player.y > self.camera_y[player.team] + screen_height:  # the top of their head is below the screen
                if self._lose_life(player):
                    self._respawn_on_platform(player)

    def _respawn_on_platform(self, player):
        """Stand the player on the last platform they were on. If that's out of
        their team's view (the camera rose since), use a teammate's last
        platform instead, highest teammate first."""
        width, height = hitbox_size(self.settings)
        platforms = self.level["platforms"]
        camera_top = self.camera_y[player.team]
        camera_bottom = camera_top + self.settings["world"]["height"]

        teammates = sorted((p for p in self.players.values()
                            if p.team == player.team and p.in_play and p is not player),
                           key=lambda p: p.y)
        for candidate in [player] + teammates:
            index = candidate.last_platform
            if index is None or index >= len(platforms):
                continue
            platform = platforms[index]
            if camera_top + height <= platform["y"] <= camera_bottom:  # on screen, with room to stand
                player.x = min(max(candidate.last_platform_x, platform["x"]),
                               platform["x"] + platform["width"] - width)
                player.y = platform["y"] - height
                break
        else:
            # No platform in view to go back to: drop in at the top of the view.
            player.y = camera_top
        _stop(player)
        self._make_invulnerable(player)
        print(f"Player {player.id} fell below the camera: back on a platform.")

    def _player_at_flag(self):
        """An in-game player touching the flag, or None (also if there's no flag)."""
        flag = self.level["flag"]
        if flag is None:
            return None
        if self.level["mode"] == RUNNER:
            flag = dict(flag, x=flag["x"] - self.scroll_x)  # it scrolls in like an obstacle
        width, height = hitbox_size(self.settings)
        for player in self.players.values():
            if player.in_play and rects_overlap(player.x, player.y, width, height,
                                                                  *flag_rect(flag, self.settings)):
                return player
        return None

    def _send_snapshots(self):
        """Send every in-game player's position, facing, jump count, speed and
        on-ground flag, and every enemy's position and AI state, to every client over UDP."""
        # vx is sent compared to what they stand on (only the walk animation uses it).
        in_game = [(p.id, p.x, p.y, p.facing, p.jump_count, round(p.vx - p.ground_vx), p.on_ground, p.invulnerable,
                    p.lives)
                   for p in self.players.values() if p.character is not None]
        enemies = [(e.id, e.x, e.y, STATES.index(e.state), ENEMY_KINDS.index(e.kind))
                   for e in self.enemies.values()]
        cameras = (self.scroll_x, self.camera_y[TEAM_BLUE], self.camera_y[TEAM_RED])
        packet = protocol.pack_snapshot(self.frame, cameras, in_game, enemies)
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
    # Enemies
    # ------------------------------------------------------------------

    def _create_enemies(self, enemy_list):
        """Make the level's enemies (each brain puts its enemy at its start).
        Runner levels have none (their platforms slide past, enemies don't)."""
        if self.level["mode"] == RUNNER:
            return
        size = self.settings["enemy"]["size"]
        for enemy_id, data in enumerate(enemy_list, start=1):
            platform = self.level["platforms"][data["platform"]]
            enemy = Enemy(id=enemy_id, platform=data["platform"], kind=data["kind"], size=size)
            self.enemies[enemy_id] = enemy
            self.enemy_brains.append(EnemyBrain(enemy, platform, data["x"], self.players, self.settings))

    def _reset_to_start(self):
        """Put the game back to the beginning: every in-game player back at
        their spawn point, standing still, and every enemy back at its start,
        patrolling. The cameras go back first, since runner spawns depend on them."""
        for team in TEAMS:
            self.camera_y[team] = 0.0  # both cameras back to the bottom
        self.scroll_x = 0.0  # and a runner level back to the start of the course
        slots = {team: 0 for team in TEAMS}  # spawn slots used so far, per team
        for player_id in self.join_order:  # oldest first, the same order they spawned in
            player = self.players[player_id]
            if player.character is None:
                continue  # still choosing a character; not in the game yet
            player.x, player.y = self._spawn_position(player, slots[player.team])
            slots[player.team] += 1
            _stop(player)
            player.lives = self.settings["player"]["lives"]  # everyone back in, with full lives
            player.last_platform = None
            player.invulnerable_left = 0.0
            player.invulnerable = False
        for brain in self.enemy_brains:
            brain.reset()

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
        connection.send({"type": protocol.LEVEL, "level": self.level})
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

    def _spawn_position(self, player, slot):
        """Spawn standing on the floor, at spawn spot number slot.

        Climb levels: on the ground on the team's side, blue from the left
        going right and red from the right going left. Runner levels: both
        teams from the left of the screen going right, blue on the middle
        floor and red on the ground. After per_row players the row starts
        over (players can overlap).
        """
        spawn = self.settings["spawn"]
        offset = (slot % spawn["per_row"]) * spawn["spacing_x"]
        height = hitbox_size(self.settings)[1]

        if self.level["mode"] == RUNNER:
            x = spawn["blue_x"] + offset
            return x, self._runner_floor_y(player, x) - height

        if player.team == TEAM_BLUE:
            x = spawn["blue_x"] + offset
        else:
            x = spawn["red_x"] - offset
        world = self.settings["world"]
        return x, world["height"] - world["ground_height"] - height


def _stop(player):
    """Clear a player's movement, e.g. after moving them somewhere new."""
    player.vx = player.vy = 0.0
    player.on_ground = False
    player.standing_on = None
    player.jump_rising = False
    player.jump_buffer_left = 0.0
    player.ground_vx = 0.0


def clamp_axis(value):
    """Turn an input value into -1, 0 or 1."""
    return max(-1, min(1, value))


def apply_input(player, input_x, input_y, jump_held, run_held):
    """Store the keys a player is holding; the physics reads them next step."""
    player.input_x = clamp_axis(input_x)
    player.input_y = clamp_axis(input_y)
    player.jump_held = bool(jump_held)
    player.run_held = bool(run_held)
