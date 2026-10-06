"""One connected client, as seen by the server.

Each connection runs two small threads:
- a reader that puts the client's messages into the server's shared inbox;
- a writer that sends queued messages, so a slow or frozen client can never
  stall the host's game loop.

Only the game loop touches game state; these threads just move bytes in
and out. (Positions go over UDP and don't pass through here.)
"""

import queue
import socket
import threading

from net import protocol

# How many unsent TCP messages a client may fall behind by before it gets
# dropped (these are rare, so a client this far behind has stopped reading).
OUTBOX_LIMIT = 120


class ClientConnection:
    def __init__(self, sock, address, inbox):
        self.id = None  # the player id, given by the server when it adds the player
        self.address = address
        self.alive = True

        # UDP: the token this client puts in its packets so the server knows
        # who sent them, and the address its packets come from (learned from
        # the first one that arrives; snapshots are sent back there).
        self.udp_token = None
        self.udp_address = None
        self._sock = sock
        self._inbox = inbox
        self._outbox = queue.Queue(maxsize=OUTBOX_LIMIT)

    def start(self):
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._write_loop, daemon=True).start()

    def send(self, message):
        self.send_encoded(protocol.encode(message))

    def send_encoded(self, data):
        """Queue already-encoded bytes (used to encode a broadcast only once)."""
        if not self.alive:
            return
        try:
            self._outbox.put_nowait(data)
        except queue.Full:
            # The client has stopped reading; drop it rather than buffer forever.
            self.close()

    def close(self):
        """Close the socket. The reader thread then reports the disconnect."""
        if not self.alive:
            return
        self.alive = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()

    def _read_loop(self):
        reader = protocol.MessageReader()
        try:
            while True:
                data = self._sock.recv(4096)
                if not data:
                    break  # the client closed the connection
                for message in reader.feed(data):
                    self._inbox.put((self, message))
        except OSError:
            pass
        self.close()
        # This is the only place a disconnect is reported, so it happens exactly once.
        self._inbox.put((self, {"type": protocol.DISCONNECTED}))

    def _write_loop(self):
        while self.alive:
            try:
                data = self._outbox.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._sock.sendall(data)
            except OSError:
                self.close()
