"""The message formats shared by the host and the clients.

Two channels are used:

TCP (reliable, ordered) for things that must arrive, sent as one JSON
object per line ("newline-delimited JSON"):

  client -> host
    choose_character   {"character": "<character id>"}

  host -> client
    welcome            {"id", "team", "token", "udp_port"}   sent once on join
    roster             {"players": [{"id", "team", "character", "is_host", "x", "y"}, ...]}
                       sent whenever someone joins, leaves or picks a character

UDP (fast, may lose or reorder packets) for data sent every frame, packed as
compact binary with the struct module:

  client -> host   input      the keys the player is holding (direction, jump, run)
  host -> client   snapshot   every player's position, facing, jump count, speed and on-ground flag,
                              and every enemy's position and AI state

A lost UDP packet is simply replaced by the next one a frame later, so
nothing ever stalls waiting for a resend (which is what TCP would do).

"connected" / "disconnected" are local-only events that the networking
threads put in a queue; they are never sent over the network.
"""

import json
import socket
import struct

# ----------------------------------------------------------------------
# TCP messages (JSON)
# ----------------------------------------------------------------------

WELCOME = "welcome"
ROSTER = "roster"
CHOOSE_CHARACTER = "choose_character"
CONNECTED = "connected"
DISCONNECTED = "disconnected"


def encode(message):
    """Turn a message dict into the bytes sent over the TCP socket."""
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


class MessageReader:
    """Rebuilds messages from a TCP byte stream.

    TCP does not keep message boundaries: one recv() can return half a
    message or several at once. Bytes are buffered until a full line
    (one complete message) has arrived.
    """

    def __init__(self):
        self._buffer = b""

    def feed(self, data):
        """Add received bytes and return every complete message in them."""
        self._buffer += data
        messages = []
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # ignore a malformed message instead of crashing
        return messages


# ----------------------------------------------------------------------
# UDP packets (binary)
# ----------------------------------------------------------------------

# The first byte of every UDP packet says what kind it is.
PACKET_INPUT = 1
PACKET_SNAPSHOT = 2

# struct format codes: "<" little-endian with no padding, B = uint8,
# H = uint16, h = int16, I = uint32, b = int8, f = float32, ? = bool.
INPUT_PACKET = struct.Struct("<BIIbbB")  # packet type, player's token, sequence number, input x, input y, buttons
SNAPSHOT_HEADER = struct.Struct("<BIBB")  # packet type, frame number, player count, enemy count
# player id, x, y, facing (1 or -1), jump count, horizontal speed (whole
# pixels per second; plenty precise for animation), on the ground. Speed
# and on-ground are only used to pick the walk animation frame.
SNAPSHOT_PLAYER = struct.Struct("<HffbBh?")
# enemy id, x, y, AI state (its index in entities.enemy.STATES).
SNAPSHOT_ENEMY = struct.Struct("<HffB")

# Bits of the input packet's buttons byte (several can be set at once).
BUTTON_JUMP = 1
BUTTON_RUN = 2

# Big enough for any packet we send (20 players is about 200 bytes).
MAX_PACKET_SIZE = 2048


def pack_input(token, sequence, input_x, input_y, jump_held, run_held):
    buttons = 0
    if jump_held:
        buttons |= BUTTON_JUMP
    if run_held:
        buttons |= BUTTON_RUN
    return INPUT_PACKET.pack(PACKET_INPUT, token, sequence, input_x, input_y, buttons)


def unpack_input(data):
    """Return (token, sequence, input_x, input_y, jump_held, run_held), or None if malformed."""
    try:
        _, token, sequence, input_x, input_y, buttons = INPUT_PACKET.unpack(data)
    except struct.error:
        return None
    return token, sequence, input_x, input_y, bool(buttons & BUTTON_JUMP), bool(buttons & BUTTON_RUN)


def pack_snapshot(frame, players, enemies):
    """players: list of (player_id, x, y, facing, jump_count, vx, on_ground).
    enemies: list of (enemy_id, x, y, state_index). All players come first, then all enemies."""
    data = SNAPSHOT_HEADER.pack(PACKET_SNAPSHOT, frame, len(players), len(enemies))
    for player in players:
        data += SNAPSHOT_PLAYER.pack(*player)
    for enemy in enemies:
        data += SNAPSHOT_ENEMY.pack(*enemy)
    return data


def unpack_snapshot(data):
    """Return (frame, players, enemies), or None if the packet is malformed."""
    try:
        _, frame, player_count, enemy_count = SNAPSHOT_HEADER.unpack_from(data, 0)
        offset = SNAPSHOT_HEADER.size
        players = []
        for _ in range(player_count):
            players.append(SNAPSHOT_PLAYER.unpack_from(data, offset))
            offset += SNAPSHOT_PLAYER.size
        enemies = []
        for _ in range(enemy_count):
            enemies.append(SNAPSHOT_ENEMY.unpack_from(data, offset))
            offset += SNAPSHOT_ENEMY.size
    except struct.error:
        return None
    return frame, players, enemies


def make_udp_socket(port=0):
    """Create a non-blocking UDP socket bound to port (0 = any free port)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", port))
    sock.setblocking(False)
    # Windows quirk: if a packet we sent earlier hit a closed port, the next
    # recvfrom() raises ConnectionResetError. Turn that behaviour off.
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        sock.ioctl(socket.SIO_UDP_CONNRESET, False)
    return sock
