"""Dedicated server entry point.

Start this before any players join:
    python src/server.py
It prints the address players should connect to. The first player to
connect becomes the host.
"""

import argparse

from core.settings import load_characters, load_settings
from net.game_server import GameServer


def main():
    settings = load_settings()

    parser = argparse.ArgumentParser(description="Run the dedicated game server.")
    parser.add_argument("--port", type=int, default=settings["network"]["port"],
                        help="port to listen on (default from data/settings.json)")
    args = parser.parse_args()

    GameServer(settings, load_characters(), args.port).serve_forever()


if __name__ == "__main__":
    main()
