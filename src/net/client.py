"""The client's connection to the dedicated server.

TCP: a background thread connects and keeps reading, so the game loop never
freezes waiting on the network. Received messages go into a queue that the
game drains once per frame with poll().

UDP: a non-blocking socket. The game sends a commands packet every frame with
send_udp() and reads any waiting snapshots with poll_udp(); neither call ever
waits.
"""

import queue
import socket
import threading

from net import protocol

CONNECT_TIMEOUT = 5.0  # seconds


class NetworkClient:
    def __init__(self, address, port):
        self.address = address
        self.port = port
        self.connected = False
        self._sock = None
        self._incoming = queue.Queue()

        self._udp = protocol.make_udp_socket()
        self._udp_target = None  # (server ip, udp port), known after the welcome message

        threading.Thread(target=self._run, daemon=True).start()

    # ------------------------------------------------------------------
    # TCP
    # ------------------------------------------------------------------

    def _run(self):
        """Background thread: connect, then read messages until the connection ends."""
        try:
            sock = socket.create_connection((self.address, self.port), timeout=CONNECT_TIMEOUT)
            sock.settimeout(None)
            # Send small messages immediately instead of batching them (lower latency).
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock = sock
            self.connected = True

            reader = protocol.MessageReader()
            while True:
                data = sock.recv(4096)
                if not data:
                    break  # the server closed the connection
                for message in reader.feed(data):
                    self._incoming.put(message)
        except OSError:
            pass

        if self.connected:
            reason = "Lost connection to the server."
        else:
            reason = f"Could not connect to a server at {self.address}:{self.port}."
        self.connected = False
        self._incoming.put({"type": protocol.DISCONNECTED, "reason": reason})

    def send(self, message):
        """Send a TCP message to the server. Does nothing if not connected."""
        if not self.connected:
            return
        try:
            self._sock.sendall(protocol.encode(message))
        except OSError:
            pass  # the reader thread will notice and report the disconnect

    def poll(self):
        """Return every TCP message received since the last call."""
        messages = []
        while True:
            try:
                messages.append(self._incoming.get_nowait())
            except queue.Empty:
                return messages

    # ------------------------------------------------------------------
    # UDP
    # ------------------------------------------------------------------

    def set_udp_port(self, udp_port):
        """Called when the welcome message says which port the server's UDP uses."""
        try:
            server_ip = socket.gethostbyname(self.address)
        except OSError:
            return
        self._udp_target = (server_ip, udp_port)

    def send_udp(self, data):
        if self._udp_target is None:
            return
        try:
            self._udp.sendto(data, self._udp_target)
        except OSError:
            pass  # UDP is best effort; the next packet follows next frame

    def poll_udp(self):
        """Return every UDP packet from the server received since the last call."""
        packets = []
        while True:
            try:
                data, sender = self._udp.recvfrom(protocol.MAX_PACKET_SIZE)
            except BlockingIOError:
                return packets  # nothing left to read
            except OSError:
                continue  # a bad packet; skip it
            if self._udp_target is not None and sender[0] == self._udp_target[0]:
                packets.append(data)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
        self._udp.close()
