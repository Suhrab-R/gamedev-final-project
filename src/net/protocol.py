"""The message formats shared by the server and the clients.

Two channels are used:

TCP (reliable, ordered) for things that must arrive, sent as one JSON
object per line ("newline-delimited JSON"):

  client -> server
    choose_character   {"character": "<character id>"}

  server -> client
    welcome            {"id", "team", "token", "udp_port"}   sent once on join
    roster             {"players": [{"id", "team", "character", "is_host"}, ...]}
                       sent whenever someone joins, leaves or picks a character

UDP (fast, may lose or reorder packets) for data sent many times per second,
packed as compact binary with the struct module:

  client -> server   commands   the player's held keys, one numbered command per frame
  server -> client   snapshot   every player's position, sent snapshot_rate times a second

A lost UDP packet is simply replaced by the next one, so nothing ever stalls
waiting for a resend (which is what TCP would do).

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
PACKET_COMMANDS = 1
PACKET_SNAPSHOT = 2

# struct format codes: "<" little-endian with no padding, B = uint8,
# H = uint16, I = uint32, b = int8, f = float32.
COMMANDS_HEADER = struct.Struct("<BIB")  # packet type, player's token, command count
COMMAND = struct.Struct("<Ibbf")  # sequence number, input x, input y, frame dt
SNAPSHOT_HEADER = struct.Struct("<BIB")  # packet type, server tick, player count
SNAPSHOT_PLAYER = struct.Struct("<HffI")  # player id, x, y, last command applied

# Each commands packet repeats the newest few commands, so one lost packet
# doesn't lose any input (the next packet carries it again).
COMMANDS_PER_PACKET = 3

# The longest frame one command may cover, in seconds. Both sides clamp to
# this, so a lag spike can't teleport a player.
MAX_COMMAND_DT = 0.1

# Big enough for any packet we send (20 players is about 300 bytes).
MAX_PACKET_SIZE = 2048


def pack_commands(token, commands):
    """commands: list of (sequence, input_x, input_y, dt), oldest first."""
    data = COMMANDS_HEADER.pack(PACKET_COMMANDS, token, len(commands))
    for command in commands:
        data += COMMAND.pack(*command)
    return data


def unpack_commands(data):
    """Return (token, commands), or None if the packet is malformed."""
    try:
        _, token, count = COMMANDS_HEADER.unpack_from(data, 0)
        commands = [
            COMMAND.unpack_from(data, COMMANDS_HEADER.size + i * COMMAND.size)
            for i in range(count)
        ]
    except struct.error:
        return None
    return token, commands


def pack_snapshot(tick, players):
    """players: list of (player_id, x, y, last_command_seq)."""
    data = SNAPSHOT_HEADER.pack(PACKET_SNAPSHOT, tick, len(players))
    for player in players:
        data += SNAPSHOT_PLAYER.pack(*player)
    return data


def unpack_snapshot(data):
    """Return (tick, players), or None if the packet is malformed."""
    try:
        _, tick, count = SNAPSHOT_HEADER.unpack_from(data, 0)
        players = [
            SNAPSHOT_PLAYER.unpack_from(data, SNAPSHOT_HEADER.size + i * SNAPSHOT_PLAYER.size)
            for i in range(count)
        ]
    except struct.error:
        return None
    return tick, players


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
