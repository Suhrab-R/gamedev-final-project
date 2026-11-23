"""The game application.

Game owns the window, the session (hosting or joining, see net/session.py)
and the state machine that decides which screen is active.

Screen size: the game is always drawn onto a fixed-size "canvas" of
world.width x world.height pixels (an off-screen RenderTexture), and that
canvas is then stretched to fit the real window. So every position in the
game is in canvas pixels, and the game looks the same on a 1080p laptop, a
1440p monitor, a resized window or fullscreen; only the stretch changes.
"""

from pyray import *

from core.assets import Assets
from core.settings import reload_settings
from core.state_machine import StateMachine
from states.character_select import CharacterSelectState
from ui.draw import draw_character, draw_notice

WINDOW_TITLE = "Final Project"
NOTICE_SECONDS = 2.5  # how long the "settings reloaded" message stays up
# If the window's shape differs from the canvas's by less than this (1%), the
# canvas is stretched to fill it exactly instead of getting black bars; a
# stretch that small can't be seen.
MAX_INVISIBLE_STRETCH = 0.01


class Game:
    def __init__(self, settings, characters, session):
        self.settings = settings
        self.characters = characters
        self.session = session
        # The canvas size (see the top of this file). Everything is drawn in
        # these units, whatever size the real window is. It's fixed once the
        # game starts, so editing world width/height needs a restart.
        self.screen_width = settings["world"]["width"]
        self.screen_height = settings["world"]["height"]
        self.states = StateMachine()
        self.assets = None  # loaded in run(), once the window exists
        self.canvas = None  # the RenderTexture everything is drawn on, made in run()

        # A short message shown at the bottom of the screen (e.g. after F5).
        self.notice = ""
        self.notice_time_left = 0.0

    def draw_player_character(self, character_id, x, y, width, height, team, facing=1, sprite_scale=None,
                              frame="idle", tint=WHITE):
        """Draw a character (sprite frame or placeholder rectangle) in the box at (x, y)."""
        if sprite_scale is None:
            sprite_scale = self.settings["player"]["scale"]
        texture = self.assets.character_texture(character_id, team, frame)
        draw_character(texture, x, y, width, height, team, facing, sprite_scale, tint)

    def show_notice(self, text):
        """Show a short message at the bottom of the screen for a few seconds."""
        self.notice = text
        self.notice_time_left = NOTICE_SECONDS

    def my_player(self):
        """This computer's own Player, or None until it has one."""
        return self.session.players.get(self.session.my_id)

    def run(self):
        set_config_flags(ConfigFlags.FLAG_WINDOW_RESIZABLE)
        init_window(self.screen_width, self.screen_height, WINDOW_TITLE)
        self._size_window_to_monitor()
        set_target_fps(self.settings["client"]["fps"])
        init_audio_device()
        set_master_volume(self.settings["audio"]["master_volume"])
        # Load every texture and sound once, now that the window and audio
        # device exist (see core/assets.py).
        self.assets = Assets(self.characters)
        self.canvas = load_render_texture(self.screen_width, self.screen_height)
        self._apply_canvas_filter()
        self.states.change(CharacterSelectState(self))

        # Main loop. Update first (the current state reads this frame's keys and
        # sends them, then the session runs the network and, on the host, the
        # server), then draw the result.
        while not window_should_close():
            dt = get_frame_time()
            if is_key_pressed(KeyboardKey.KEY_F11):
                # "Borderless" fullscreen: a window covering the whole screen.
                # (Real fullscreen would switch the monitor's resolution.)
                toggle_borderless_windowed()
            self._check_settings_reload(dt)
            self.states.update(dt)
            self.session.update(dt)

            # Draw the game onto the canvas, then stretch the canvas to the window.
            begin_texture_mode(self.canvas)
            self.states.render()
            if self.notice_time_left > 0:
                draw_notice(self.notice, self.screen_width, self.screen_height)
            end_texture_mode()

            begin_drawing()
            clear_background(BLACK)  # shows as bars if the window's shape differs
            self._draw_canvas_to_window()
            end_drawing()

        self.session.close()
        unload_render_texture(self.canvas)
        self.assets.unload()
        close_audio_device()
        close_window()

    def _size_window_to_monitor(self):
        """Open the window at the same share of the screen on every monitor.

        display.window_screen_fraction is how much of the monitor's height the
        window takes (0.639 = 920 px on a 1440p monitor, so exactly 1:1 with
        the canvas there, and 690 px on a 1080p one),
        so the game looks the same size on both. The window can then be
        resized by dragging, but not below min_window_scale x the canvas size,
        where the text would get too small to read.
        """
        display = self.settings["display"]
        monitor = get_current_monitor()
        monitor_width = get_monitor_width(monitor)
        monitor_height = get_monitor_height(monitor)

        scale = monitor_height * display["window_screen_fraction"] / self.screen_height
        # Never wider than 90% of the screen, for unusually narrow monitors.
        scale = min(scale, monitor_width * 0.9 / self.screen_width)
        width = int(self.screen_width * scale)
        height = int(self.screen_height * scale)

        set_window_size(width, height)
        set_window_position((monitor_width - width) // 2, (monitor_height - height) // 2)
        min_scale = display["min_window_scale"]
        set_window_min_size(int(self.screen_width * min_scale), int(self.screen_height * min_scale))

    def _apply_canvas_filter(self):
        """How the canvas is stretched: smooth (bilinear) or sharp (point).

        Smooth keeps text and thin lines readable at any window size but makes
        pixel art a little soft; sharp keeps pixels crisp but at sizes that
        aren't whole multiples some pixels come out wider than others.
        """
        if self.settings["display"]["smooth_scaling"]:
            set_texture_filter(self.canvas.texture, TextureFilter.TEXTURE_FILTER_BILINEAR)
        else:
            set_texture_filter(self.canvas.texture, TextureFilter.TEXTURE_FILTER_POINT)

    def mouse_position(self):
        """The mouse position in canvas pixels (the same units as the game),
        whatever size the window is. Can be outside the canvas (over a bar)."""
        canvas_area = self._canvas_area()
        mouse = get_mouse_position()
        x = (mouse.x - canvas_area.x) * self.screen_width / canvas_area.width
        y = (mouse.y - canvas_area.y) * self.screen_height / canvas_area.height
        return x, y

    def _draw_canvas_to_window(self):
        # The negative height flips the canvas: OpenGL stores render
        # textures upside down.
        source = Rectangle(0, 0, self.screen_width, -self.screen_height)
        # Copy the canvas's colors straight onto the window, ignoring its
        # alpha (see-through-ness). Drawing something see-through onto the
        # canvas (a decoration, a blinking player) also makes the canvas
        # itself partly see-through there; blended normally, the window's
        # black would then show through and darken it.
        rl_set_blend_factors(RL_ONE, RL_ZERO, RL_FUNC_ADD)  # new color = canvas color
        begin_blend_mode(BlendMode.BLEND_CUSTOM)
        draw_texture_pro(self.canvas.texture, source, self._canvas_area(), Vector2(0, 0), 0, WHITE)
        end_blend_mode()

    def _canvas_area(self):
        """Where in the window the canvas is drawn: as big as fits, keeping
        its shape, centered (any leftover space becomes black bars)."""
        window_width = get_screen_width()
        window_height = get_screen_height()
        scale_x = window_width / self.screen_width
        scale_y = window_height / self.screen_height

        if abs(scale_x - scale_y) / scale_y < MAX_INVISIBLE_STRETCH:
            # Nearly the same shape (e.g. a 16:9 screen, since the canvas
            # can't be exactly 16:9 in whole pixels): fill the window exactly.
            # Keeping the shape perfectly would leave a fraction-of-a-pixel
            # gap that shows as a thin dark line along the edges.
            width = window_width
            height = window_height
        else:
            scale = min(scale_x, scale_y)
            width = round(self.screen_width * scale)
            height = round(self.screen_height * scale)
        return Rectangle((window_width - width) // 2, (window_height - height) // 2, width, height)

    def _check_settings_reload(self, dt):
        """F5 re-reads data/settings.json, for tuning without restarting.

        Physics runs on the host, so press F5 in the host's window to change
        speeds and jumps for everyone. A client's own file only changes how
        that client draws things.
        """
        self.notice_time_left -= dt
        if not is_key_pressed(KeyboardKey.KEY_F5):
            return
        error = reload_settings(self.settings)
        set_master_volume(self.settings["audio"]["master_volume"])
        self._apply_canvas_filter()
        self.show_notice(error or "Reloaded data/settings.json")
