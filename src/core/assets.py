"""Loads the game's images and sounds from assets/ once, at startup.

Everything is loaded a single time when the window opens and shared by
every screen and every player that uses it, instead of being loaded each
frame or once per player. Textures can only be loaded after init_window()
(they live on the graphics card), so Game.run() creates this right after
opening the window, and unload() frees them all before the window closes.
Sounds likewise need the audio device opened first (init_audio_device()).
"""

from pathlib import Path

from pyray import *

# src/core/assets.py -> parents[2] is the repository root.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

# Sound name (used in code) -> file in assets/.
SOUND_FILES = {
    "jump": "audio/NsmbwiiJump.wav",
}


class Assets:
    def __init__(self, characters):
        # (character id, team) -> Texture, for characters drawn with a sprite.
        # Each character has one image per team (team-colored clothes), listed
        # under "sprites" in characters.json. Shared: every player on the same
        # team who picks the same character draws the same texture.
        self.character_textures = {}

        for character in characters:
            # Characters without "sprites" are placeholder shapes; nothing to load.
            for team, sprite in character.get("sprites", {}).items():
                texture = load_texture(str(ASSETS_DIR / sprite))
                if texture.id == 0:
                    # Missing or broken file: raylib logs a warning and we fall
                    # back to drawing a shape instead of crashing.
                    print(f"Could not load {sprite}; drawing a shape instead.")
                    continue
                self.character_textures[(character["id"], team)] = texture

        # Sound name -> Sound, loaded once and played whenever needed.
        self.sounds = {}
        for name, file_name in SOUND_FILES.items():
            sound = load_sound(str(ASSETS_DIR / file_name))
            if sound.frameCount == 0:
                print(f"Could not load {file_name}; that sound will be silent.")
                continue
            self.sounds[name] = sound

    def character_texture(self, character_id, team):
        """The texture for this character on this team, or None to draw a shape."""
        return self.character_textures.get((character_id, team))

    def play(self, name):
        """Play a loaded sound by name (e.g. "jump"); does nothing if it failed to load."""
        sound = self.sounds.get(name)
        if sound is not None:
            play_sound(sound)

    def unload(self):
        """Free every texture and sound. Call once, before closing the window and audio."""
        for texture in self.character_textures.values():
            unload_texture(texture)
        self.character_textures.clear()
        for sound in self.sounds.values():
            unload_sound(sound)
        self.sounds.clear()
