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

from entities.player import TEAMS

# src/core/assets.py -> parents[2] is the repository root.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

# The frame drawn when nothing more specific applies (standing still).
DEFAULT_FRAME = "idle"

# Sound name (used in code) -> file in assets/.
SOUND_FILES = {
    "jump": "audio/NsmbwiiJump.wav",
}

# Enemy sprite name (used in code) -> file in assets/. Every enemy is a
# Goomba for now: regular ones look normal, chasers have dark marks above
# their head, and a chaser's eyes turn red while it chases.
ENEMY_SPRITE_FILES = {
    "regular": "sprites/enemies/goomba.png",
    "chaser": "sprites/enemies/goomba_chaser.png",
    "chaser_chasing": "sprites/enemies/goomba_chaser_chasing.png",
}


class Assets:
    def __init__(self, characters):
        # (character id, team, frame name) -> Texture, for characters drawn
        # with sprites. Each sprite character has a folder ("sprite_folder" in
        # characters.json) holding one sub-folder per team (team-colored
        # clothes), e.g. sprites/mario/blue/idle.png. Every .png in a team
        # folder is loaded, and its file name without ".png" is the frame name
        # ("idle", later "walk_1", "jump", ...), so adding a frame needs no
        # code change here. Shared: every player on the same team who picks
        # the same character draws from the same textures.
        self.character_textures = {}

        for character in characters:
            # Characters without a sprite folder are placeholder shapes.
            folder = character.get("sprite_folder")
            if folder is None:
                continue
            for team in TEAMS:
                team_folder = ASSETS_DIR / folder / team
                # sorted() so frames load in the same order on every computer.
                for path in sorted(team_folder.glob("*.png")):
                    texture = load_texture(str(path))
                    if texture.id == 0:
                        # Broken file: raylib logs a warning and we skip it.
                        print(f"Could not load {path}; skipping it.")
                        continue
                    self.character_textures[(character["id"], team, path.stem)] = texture
                if (character["id"], team, DEFAULT_FRAME) not in self.character_textures:
                    # No idle frame means the character can't be drawn with a
                    # sprite, so it falls back to a shape instead of crashing.
                    print(f"No {DEFAULT_FRAME}.png in {team_folder}; drawing a shape instead.")

        # Enemy sprite name -> Texture, shared by every enemy that uses it.
        self.enemy_textures = {}
        for name, file_name in ENEMY_SPRITE_FILES.items():
            texture = load_texture(str(ASSETS_DIR / file_name))
            if texture.id == 0:
                print(f"Could not load {file_name}; that enemy will be drawn as a square.")
                continue
            self.enemy_textures[name] = texture

        # Sound name -> Sound, loaded once and played whenever needed.
        self.sounds = {}
        for name, file_name in SOUND_FILES.items():
            sound = load_sound(str(ASSETS_DIR / file_name))
            if sound.frameCount == 0:
                print(f"Could not load {file_name}; that sound will be silent.")
                continue
            self.sounds[name] = sound

    def character_texture(self, character_id, team, frame=DEFAULT_FRAME):
        """The texture for this character, team and frame, or None to draw a shape.

        A frame the character doesn't have yet falls back to its idle frame,
        so new animations can be added one character at a time.
        """
        texture = self.character_textures.get((character_id, team, frame))
        if texture is None:
            texture = self.character_textures.get((character_id, team, DEFAULT_FRAME))
        return texture

    def enemy_texture(self, name):
        """The enemy sprite with this name ("regular", "chaser" or
        "chaser_chasing"), or None (then it's drawn as a square)."""
        return self.enemy_textures.get(name)

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
        for texture in self.enemy_textures.values():
            unload_texture(texture)
        self.enemy_textures.clear()
        for sound in self.sounds.values():
            unload_sound(sound)
        self.sounds.clear()
