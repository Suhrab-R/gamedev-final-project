"""Game client entry point.

Start the dedicated server first (python src/server.py), then run:
    python src/main.py                          # server on this computer
    python src/main.py --server 192.168.1.20    # server elsewhere on the LAN
"""

import argparse

from core.game import Game
from core.settings import load_characters, load_settings


def main():
    settings = load_settings()

    parser = argparse.ArgumentParser(description="Join a game server.")
    parser.add_argument("--server", default="127.0.0.1",
                        help="IP address of the computer running the server (default: this computer)")
    parser.add_argument("--port", type=int, default=settings["network"]["port"],
                        help="server port (default from data/settings.json)")
    args = parser.parse_args()

    Game(settings, load_characters(), args.server, args.port).run()


if __name__ == "__main__":
    main()
