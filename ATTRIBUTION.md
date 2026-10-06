# Attribution

This file records all generative-AI assistance and all external material used in this project. It will be updated as the project develops.

## AI Use

| Assistant | File(s) | How it was used |
| --- | --- | --- |
| OpenAI Codex | `src/main.py` | Created the basic Python + Raylib starter file, converting the supplied Odin/Raylib code from the discord to Python |
| Anthropic Claude | `docs/gdd.md` | Filled in the provided GDD template fields after being given an extensive knowledge about the ideas and plans for the game. Afterwards a good amount of the fields were edited by myself, **Suhrab Roeen**. Claude was mainly used to create the structure |
| Anthropic Claude (Claude Code) | `src/main.py` | Rewrote the starter file into a single movable square (arrow keys/WASD, clamped to the window) with separate `update` and `render` functions, settings as named constants, and comments. |
| Anthropic Claude (Claude Code) | `src/` (all packages), `src/main.py`, `src/server.py`, `data/settings.json`, `data/characters.json` | Implemented the LAN multiplayer foundation from my design: a dedicated server (first client to connect is host, balanced/alternating team assignment, server-authoritative movement, snapshots to all clients), the client connection, a game state machine with a character select state and a playing state, placeholder shape characters drawn in team colors, and tuning/character data loaded from JSON files. Organized `src/` into `core/`, `entities/`, `net/`, `states/` and `ui/` packages. |
| Anthropic Claude (Claude Code) | `src/net/` (all files), `src/entities/player.py`, `src/core/game.py`, `src/states/playing.py`, `data/settings.json` | Switched position updates from TCP to UDP after I noticed the movement wasn't smooth: binary UDP packets for movement commands and position snapshots (TCP kept for joining and the roster), client-side prediction for your own player, and interpolation between snapshots for other players. |
| Anthropic Claude (Claude Code) | `src/core/game.py`, `src/states/playing.py`, `src/net/client_sync.py`, `data/settings.json` | Removed the interpolation delay after I found remote movement lagged behind: snapshots now go out every server tick (60/s) and other players are drawn at their newest position. |
| Anthropic Claude (Claude Code) | `src/net/` (all files, new `session.py`), `src/core/game.py`, `src/main.py`, `src/entities/player.py`, `src/states/`, `data/settings.json`; removed `src/server.py`, `src/net/client_sync.py` | Replaced the dedicated server with a listen server that runs inside the host's game (`--host`), and switched to my test game's movement model after I found it smoother: clients send held keys every frame, the host moves everyone each frame and sends positions back, and the host's screen draws the server's players directly. Added host/client sessions so the game states work the same either way. |

<!-- Example:
| Assistant name | File or feature | What the assistant generated, changed, explained, or helped debug. |
-->