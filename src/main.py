"""Game entry point.

The host runs the game with --host; the game then also runs the server that
everyone else connects to. Everyone else joins with the host's IP address:
    python src/main.py --host                   # host a game on this computer
    python src/main.py --server 192.168.1.20    # join the host at that address
    python src/main.py                          # join a host on this same computer
"""

import argparse

from core.game import Game
from core.settings import load_characters, load_settings
from net.session import ClientSession, HostSession


def main():
    settings = load_settings()
    characters = load_characters()

    parser = argparse.ArgumentParser(description="Host or join a game.")
    parser.add_argument("--host", action="store_true",
                        help="host the game on this computer (everyone else joins you)")
    parser.add_argument("--server", default="127.0.0.1",
                        help="IP address of the host to join (default: this computer)")
    parser.add_argument("--port", type=int, default=settings["network"]["port"],
                        help="port to host on or join (default from data/settings.json)")
    args = parser.parse_args()

    if args.host:
        session = HostSession(settings, characters, args.port)
    else:
        session = ClientSession(args.server, args.port)
    Game(settings, characters, session).run()


if __name__ == "__main__":
    main()
