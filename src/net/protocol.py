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

  client -> host   input      the movement keys the player is holding
  host -> client   snapshot   every player's position

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
# H = uint16, I = uint32, b = int8, f = float32.
INPUT_PACKET = struct.Struct("<BIIbb")  # packet type, player's token, sequence number, input x, input y
SNAPSHOT_HEADER = struct.Struct("<BIB")  # packet type, frame number, player count
SNAPSHOT_PLAYER = struct.Struct("<Hff")  # player id, x, y

# Big enough for any packet we send (20 players is about 200 bytes).
MAX_PACKET_SIZE = 2048


def pack_input(token, sequence, input_x, input_y):
    return INPUT_PACKET.pack(PACKET_INPUT, token, sequence, input_x, input_y)


def unpack_input(data):
    """Return (token, sequence, input_x, input_y), or None if the packet is malformed."""
    try:
        _, token, sequence, input_x, input_y = INPUT_PACKET.unpack(data)
    except struct.error:
        return None
    return token, sequence, input_x, input_y


def pack_snapshot(frame, players):
    """players: list of (player_id, x, y)."""
    data = SNAPSHOT_HEADER.pack(PACKET_SNAPSHOT, frame, len(players))
    for player in players:
        data += SNAPSHOT_PLAYER.pack(*player)
    return data


def unpack_snapshot(data):
    """Return (frame, players), or None if the packet is malformed."""
    try:
        _, frame, count = SNAPSHOT_HEADER.unpack_from(data, 0)
        players = [
            SNAPSHOT_PLAYER.unpack_from(data, SNAPSHOT_HEADER.size + i * SNAPSHOT_PLAYER.size)
            for i in range(count)
        ]
    except struct.error:
        return None
    return frame, players


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
