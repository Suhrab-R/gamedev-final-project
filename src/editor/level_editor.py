"""The host's in-game level editor (a development tool, not part of the game).

Press E while hosting to switch edit mode on or off. In edit mode:

    1  one-way platform   drag with the left mouse button to draw it
    2  solid platform     drag to draw it
    3  regular enemy      click on (or just above) a platform
    4  chaser enemy       click on (or just above) a platform
    5  flag               click where it should stand (there is only one)
    6  place me           click to put your own character there (on the platform under the mouse)
    7  decoration         drag to draw a see-through block with no collision, for
                          building arrows and other hints for players out of blocks
    8  pit                runner levels: drag sideways to remove the ground there
                          (right-click in the gap to fill it back in)
    Ctrl + drag           move a platform (its enemies come with it), decoration, enemy or the flag
    Right-click           delete what's under the mouse (a platform takes its enemies
                          with it). Where a decoration and a platform overlap, the
                          decoration is picked while tool 7 is selected.
    M                     mirror mode: placing, moving and deleting platforms and
                          enemies also does the same for the other team. Climb
                          levels: on the other side of the middle line. Runner
                          levels: in the same spot in the other lane, up to
                          where the lanes merge. (The flag isn't mirrored;
                          there's only one.)

Runner levels: while edit mode is on the screen stops scrolling, and the
arrow keys or the mouse wheel move along the course (SHIFT = faster, HOME =
back to the start). Leaving edit mode carries on scrolling from there.

F (in or out of edit mode) toggles fly mode: WASD flies your character
through everything, SHIFT flies faster, and your team's camera follows you
down as well as up.

Everything snaps to half a block (hold ALT to place exactly at the mouse
instead). In edit mode an outline follows the mouse showing exactly where
the selected tool will put things. Every change is saved to the level's file
in data/ (e.g. data/level2.json) straight away and sent to every player, so
they see it instantly. The editor also watches that file, so saving it from
a text editor reloads the level too (with or without edit mode on).
"""

import copy
import os

from pyray import *

from core.level import (
    CHASER, REGULAR, RUNNER, clean_level, flag_rect, level_path, load_level, save_level, split_end_x,
)
from entities.player import hitbox_size
from ui.draw import TEXT_COLOR, draw_grid

TOOLS = {
    KeyboardKey.KEY_ONE: "one-way platform",
    KeyboardKey.KEY_TWO: "solid platform",
    KeyboardKey.KEY_THREE: "regular enemy",
    KeyboardKey.KEY_FOUR: "chaser enemy",
    KeyboardKey.KEY_FIVE: "flag",
    KeyboardKey.KEY_SIX: "place me",
    KeyboardKey.KEY_SEVEN: "decoration",
    KeyboardKey.KEY_EIGHT: "pit",
}
DRAG_TOOLS = ("one-way platform", "solid platform", "decoration", "pit")  # drawn by dragging out a box
FILE_CHECK_SECONDS = 0.5  # how often to look for outside changes to the level file
SCROLL_SPEED = 900  # runner levels: how fast the arrow keys move along the course (px/s)
SCROLL_FAST_SPEED = 3000  # with SHIFT held
WHEEL_STEP = 200  # pixels per mouse wheel notch

PREVIEW_COLOR = Color(40, 120, 255, 255)
ENEMY_START_COLOR = Color(200, 40, 40, 255)
MIRROR_LINE_COLOR = Color(160, 60, 200, 255)
PANEL_COLOR = Color(255, 255, 255, 225)


class LevelEditor:
    def __init__(self, game):
        self.game = game
        self.active = False
        self.mirror = False
        self.tool = "one-way platform"
        self.drag_start = None  # where a platform drag started (snapped), or None
        # During Ctrl + drag: (what, index, grab offset x, grab offset y, index of its mirror or None)
        self.moving = None
        self.file_check_left = FILE_CHECK_SECONDS
        self.file_time = self._file_time()

    # ------------------------------------------------------------------
    # Every frame
    # ------------------------------------------------------------------

    def update(self, dt):
        self._watch_file(dt)
        session = self.game.session
        if is_key_pressed(KeyboardKey.KEY_F):
            session.set_flying(not session.is_flying())
            self.game.show_notice("Fly mode on (WASD, SHIFT = faster, F to stop)" if session.is_flying()
                                  else "Fly mode off")
        if is_key_pressed(KeyboardKey.KEY_E):
            self.active = not self.active
            self.drag_start = self.moving = None
            session.set_scroll_paused(self.active)  # a runner level holds still while editing
            self.game.show_notice("Edit mode on (E to leave)" if self.active else "Edit mode off")
        if not self.active:
            return
        if self.level["mode"] == RUNNER:
            self._scroll_course(dt)

        for key, tool in TOOLS.items():
            if is_key_pressed(key):
                self.tool = tool
        if is_key_pressed(KeyboardKey.KEY_M):
            self.mirror = not self.mirror
            self.game.show_notice("Mirror mode on" if self.mirror else "Mirror mode off")

        mouse_x, mouse_y = self._mouse()
        ctrl = is_key_down(KeyboardKey.KEY_LEFT_CONTROL) or is_key_down(KeyboardKey.KEY_RIGHT_CONTROL)

        if is_mouse_button_pressed(MouseButton.MOUSE_BUTTON_RIGHT):
            self._delete_at(mouse_x, mouse_y)
        elif is_mouse_button_pressed(MouseButton.MOUSE_BUTTON_LEFT):
            if ctrl:
                self._start_move(mouse_x, mouse_y)
            elif self.tool in DRAG_TOOLS:
                self.drag_start = (self._snap(mouse_x), self._snap(mouse_y))
            elif "enemy" in self.tool:
                self._place_enemy(mouse_x, mouse_y, REGULAR if self.tool == "regular enemy" else CHASER)
            elif self.tool == "flag":
                self._place_flag(mouse_x, mouse_y)
            else:
                self._place_me(mouse_x, mouse_y)

        if is_mouse_button_released(MouseButton.MOUSE_BUTTON_LEFT):
            if self.drag_start is not None:
                self._finish_box(mouse_x, mouse_y)
            elif self.moving is not None:
                self._finish_move(mouse_x, mouse_y)

    def _scroll_course(self, dt):
        """Runner levels: arrow keys / mouse wheel move along the course."""
        shift = is_key_down(KeyboardKey.KEY_LEFT_SHIFT) or is_key_down(KeyboardKey.KEY_RIGHT_SHIFT)
        speed = SCROLL_FAST_SPEED if shift else SCROLL_SPEED
        x = self.game.session.scroll_x
        if is_key_down(KeyboardKey.KEY_RIGHT):
            x += speed * dt
        if is_key_down(KeyboardKey.KEY_LEFT):
            x -= speed * dt
        x -= get_mouse_wheel_move() * WHEEL_STEP  # wheel up = back toward the start
        if is_key_pressed(KeyboardKey.KEY_HOME):
            x = 0
        self.game.session.set_scroll(x)

    def render_background(self):
        """In edit mode, a block grid behind the level to line things up with.
        Drawn through the camera, like render_world."""
        if self.active:
            draw_grid(self.game.settings["world"], self.game.session.scroll_x, self._camera_y())

    def render_world(self):
        """The editor's markers in the level (drawn through the camera)."""
        if not self.active:
            return
        mouse_x, mouse_y = self._mouse()
        top = self._camera_y()
        if self.level["mode"] == RUNNER:
            # Where the lanes merge (mirror mode stops copying past here).
            line_x = split_end_x(self.level)
            draw_line_ex(Vector2(line_x, top), Vector2(line_x, top + self.game.screen_height), 2, MIRROR_LINE_COLOR)
            draw_text("lanes merge", int(line_x) + 6, int(top) + 140, 18, MIRROR_LINE_COLOR)
        elif self.mirror:
            line_x = self._mirror_line()
            draw_line_ex(Vector2(line_x, top), Vector2(line_x, top + self.game.screen_height), 2, MIRROR_LINE_COLOR)

        # Where each enemy starts (they walk away from it while playing),
        # since that's what moving and deleting enemies works with.
        for index in range(len(self.level["enemies"])):
            x, y, size, _ = self._enemy_rect(index)
            draw_rectangle_lines_ex(Rectangle(x, y, size, size), 2, ENEMY_START_COLOR)

        if self.drag_start is not None:
            x, y, width, height = self._platform_rect(*self.drag_start, mouse_x, mouse_y)
            if self.tool == "pit":  # a pit only has a left and right: show it across the ground
                world = self.game.settings["world"]
                y, height = world["height"] - world["ground_height"], world["ground_height"]
            draw_rectangle_lines_ex(Rectangle(x, y, width, height), 2, PREVIEW_COLOR)
        if self.moving is not None:
            x, y, width, height = self._moved_rect(mouse_x, mouse_y)
            draw_rectangle_lines_ex(Rectangle(x, y, width, height), 2, PREVIEW_COLOR)
        if self.drag_start is None and self.moving is None:
            self._draw_cursor_preview(mouse_x, mouse_y)

    def _draw_cursor_preview(self, mouse_x, mouse_y):
        """Show where a click with the selected tool would put things (after
        snapping), so there are no surprises."""
        tool = self.tool
        if tool in DRAG_TOOLS:
            # A crosshair on the snapped point a drag would start from.
            x, y = self._snap(mouse_x), self._snap(mouse_y)
            draw_line_ex(Vector2(x - 10, y), Vector2(x + 10, y), 2, PREVIEW_COLOR)
            draw_line_ex(Vector2(x, y - 10), Vector2(x, y + 10), 2, PREVIEW_COLOR)
            return
        if tool == "flag":
            _, _, width, height = flag_rect({"x": 0, "y": 0}, self.game.settings)
            box = (self._snap(mouse_x - width / 2), self._snap(mouse_y) - height, width, height)
        else:
            index = self._platform_under(mouse_x, mouse_y)
            if "enemy" in tool:
                if index is None or self.level["mode"] == RUNNER:
                    # Nowhere to put an enemy here: a small red X.
                    draw_line_ex(Vector2(mouse_x - 8, mouse_y - 8), Vector2(mouse_x + 8, mouse_y + 8), 2,
                                 ENEMY_START_COLOR)
                    draw_line_ex(Vector2(mouse_x - 8, mouse_y + 8), Vector2(mouse_x + 8, mouse_y - 8), 2,
                                 ENEMY_START_COLOR)
                    return
                size = self.game.settings["enemy"]["size"]
                top = self.level["platforms"][index]["y"]
                box = (self._snap(mouse_x) - size / 2, top - size, size, size)
            else:  # place me (same position as _place_me)
                width, height = hitbox_size(self.game.settings)
                feet_y = self.level["platforms"][index]["y"] if index is not None else mouse_y
                box = (mouse_x - width / 2, feet_y - height, width, height)
        draw_rectangle_lines_ex(Rectangle(*box), 2, PREVIEW_COLOR)

    def render(self):
        """The help panel (fixed on the screen, only in edit mode)."""
        if self.active:
            self._draw_help()

    # ------------------------------------------------------------------
    # Placing, moving and deleting
    # ------------------------------------------------------------------

    def _finish_box(self, mouse_x, mouse_y):
        """A drag has ended: add the platform or decoration it drew."""
        x, y, width, height = self._platform_rect(*self.drag_start, mouse_x, mouse_y)
        self.drag_start = None
        level = self._copy_level()
        if self.tool == "pit":
            if level["mode"] != RUNNER:
                self.game.show_notice("Pits are only for runner levels")
                return
            level["pits"].append({"x": x, "width": width})
            self._apply(level, "Added a pit")
            return
        box = {"x": x, "y": y, "width": width, "height": height}
        if self.tool == "decoration":
            kind = "decorations"
        else:
            kind = "platforms"
            box["solid"] = self.tool == "solid platform"
        level[kind].append(box)
        mirrored = self._mirror_box(x, y, width, height)
        if self.mirror and mirrored is not None and mirrored != (x, y):
            level[kind].append(dict(box, x=mirrored[0], y=mirrored[1]))
        self._apply(level, f"Added a {self.tool}")

    def _place_enemy(self, mouse_x, mouse_y, kind):
        if self.level["mode"] == RUNNER:
            self.game.show_notice("Runner levels don't have enemies (yet)")
            return
        index = self._platform_under(mouse_x, mouse_y)
        if index is None:
            self.game.show_notice("Click on or just above a platform to put an enemy there")
            return
        level = self._copy_level()
        x = self._snap(mouse_x)
        level["enemies"].append({"platform": index, "x": x, "kind": kind})
        if self.mirror:
            mirrored = self._mirror_enemy_spot(x, self.level["platforms"][index]["y"])
            if mirrored is not None:
                level["enemies"].append({"platform": mirrored[1], "x": mirrored[0], "kind": kind})
        self._apply(level, f"Added a {kind} enemy")

    def _place_flag(self, mouse_x, mouse_y):
        level = self._copy_level()
        _, _, width, height = flag_rect({"x": 0, "y": 0}, self.game.settings)
        # The mouse is where the bottom middle of the pole goes.
        level["flag"] = {"x": self._snap(mouse_x - width / 2), "y": self._snap(mouse_y) - height}
        self._apply(level, "Moved the flag")

    def _place_me(self, mouse_x, mouse_y):
        """Put the host's character at the mouse: standing on the platform
        under it if there is one, otherwise with its feet at the mouse."""
        width, height = hitbox_size(self.game.settings)
        index = self._platform_under(mouse_x, mouse_y)
        feet_y = self.level["platforms"][index]["y"] if index is not None else mouse_y
        # Players are in screen positions; a runner level's course is scrolled by scroll_x.
        screen_x = mouse_x - self.game.session.scroll_x
        self.game.session.place_my_player(screen_x - width / 2, feet_y - height)

    def _delete_at(self, x, y):
        level = self._copy_level()
        enemy = self._enemy_at(x, y)
        if enemy is not None:
            doomed = {enemy}
            if self.mirror:
                doomed.add(self._mirror_enemy(enemy))
            level["enemies"] = [e for i, e in enumerate(level["enemies"]) if i not in doomed]
            self._apply(level, "Deleted an enemy")
        elif self._flag_at(x, y):
            level["flag"] = None
            self._apply(level, "Deleted the flag")
        elif self._pit_at(x, y) is not None:
            del level["pits"][self._pit_at(x, y)]
            self._apply(level, "Filled in a pit")
        elif self._decoration_picked(x, y) is not None:
            decoration = self._decoration_picked(x, y)
            doomed = {decoration}
            if self.mirror:
                doomed.add(self._mirror_decoration(decoration))
            level["decorations"] = [d for i, d in enumerate(level["decorations"]) if i not in doomed]
            self._apply(level, "Deleted a decoration")
        else:
            platform = self._platform_at(x, y)
            if platform is None:
                return
            doomed = {platform}
            if self.mirror:
                doomed.add(self._mirror_platform(platform))
            doomed.discard(None)
            # A platform's enemies go with it, and enemies on later platforms
            # now point at a lower index (one lower per deleted platform before theirs).
            level["platforms"] = [p for i, p in enumerate(level["platforms"]) if i not in doomed]
            level["enemies"] = [dict(e, platform=e["platform"] - sum(1 for d in doomed if d < e["platform"]))
                                for e in level["enemies"] if e["platform"] not in doomed]
            self._apply(level, "Deleted a platform")

    def _start_move(self, x, y):
        """Grab whatever is under the mouse (an enemy first, then the flag, then a platform)."""
        enemy = self._enemy_at(x, y)
        if enemy is not None:
            self.moving = ("enemy", enemy, 0, 0, self._mirror_enemy(enemy) if self.mirror else None)
            return
        level = self.level
        if self._flag_at(x, y):
            self.moving = ("flag", None, x - level["flag"]["x"], y - level["flag"]["y"], None)
            return
        decoration = self._decoration_picked(x, y)
        if decoration is not None:
            data = level["decorations"][decoration]
            mirror = self._mirror_decoration(decoration) if self.mirror else None
            self.moving = ("decoration", decoration, x - data["x"], y - data["y"], mirror)
            return
        platform = self._platform_at(x, y)
        if platform is not None:
            data = level["platforms"][platform]
            mirror = self._mirror_platform(platform) if self.mirror else None
            self.moving = ("platform", platform, x - data["x"], y - data["y"], mirror)

    def _finish_move(self, mouse_x, mouse_y):
        what, index, _, _, mirror = self.moving
        x, y, width, _ = self._moved_rect(mouse_x, mouse_y)
        self.moving = None
        level = self._copy_level()
        if what == "platform":
            self._move_platform(level, index, x, y)
            height = level["platforms"][index]["height"]
            mirrored = self._mirror_box(x, y, width, height)
            if mirror is not None and mirrored is not None:
                self._move_platform(level, mirror, *mirrored)
        elif what == "decoration":
            level["decorations"][index].update(x=x, y=y)
            height = level["decorations"][index]["height"]
            mirrored = self._mirror_box(x, y, width, height)
            if mirror is not None and mirrored is not None:
                level["decorations"][mirror].update(x=mirrored[0], y=mirrored[1])
        elif what == "flag":
            level["flag"] = {"x": x, "y": y}
        else:
            platform = self._platform_under(mouse_x, mouse_y)
            if platform is None:
                self.game.show_notice("Enemies have to go on a platform")
                return
            level["enemies"][index].update(platform=platform, x=self._snap(mouse_x))
            mirrored = self._mirror_enemy_spot(self._snap(mouse_x), self.level["platforms"][platform]["y"])
            if mirror is not None and mirrored is not None:
                level["enemies"][mirror].update(platform=mirrored[1], x=mirrored[0])
        self._apply(level, f"Moved the {what}")

    @staticmethod
    def _move_platform(level, index, x, y):
        platform = level["platforms"][index]
        dx = x - platform["x"]
        platform["x"], platform["y"] = x, y
        for enemy in level["enemies"]:
            if enemy["platform"] == index:
                enemy["x"] += dx  # its enemies ride along

    def _apply(self, level, message):
        """Use the changed level: save it, send it to everyone, say what happened."""
        level = clean_level(level)
        save_level(level, self.game.session.level_file)
        self.file_time = self._file_time()  # our own save isn't an outside change
        self.game.session.set_level(level)
        self.game.show_notice(message)

    # ------------------------------------------------------------------
    # Mirror mode
    # ------------------------------------------------------------------

    def _mirror_line(self):
        """Climb levels: the x of the middle line things are mirrored across
        (snapped, so mirrored things stay on the grid)."""
        return self._snap(self.game.settings["world"]["width"] / 2)

    def _mirror_box(self, x, y, width, height):
        """Where the other team's copy of a width x height box at (x, y) goes,
        as its new (x, y), or None if it has no copy.

        Climb levels: flipped across the middle line. Runner levels: the same
        spot in the other lane (moved down or up by the distance between the
        two lanes' floors), but only before the lanes merge.
        """
        level = self.level
        if level["mode"] != RUNNER:
            return 2 * self._mirror_line() - x - width, y
        if x + width > split_end_x(level):
            return None  # the lanes have merged: both teams share this part
        world = self.game.settings["world"]
        lane_gap = (world["height"] - world["ground_height"]) - level["split"]["y"]
        if y < level["split"]["y"]:
            return x, y + lane_gap  # top lane -> bottom lane
        return x, y - lane_gap  # bottom lane -> top lane

    def _mirror_enemy_spot(self, x, platform_y):
        """Where the copy of an enemy standing at x on a platform whose top is
        platform_y goes: (x, platform index), or None if there's nowhere."""
        size = self.game.settings["enemy"]["size"]
        mirrored = self._mirror_box(x - size / 2, platform_y - size, size, size)
        if mirrored is None:
            return None
        mirror_x = mirrored[0] + size / 2
        mirror_feet = mirrored[1] + size
        if (mirror_x, mirror_feet) == (x, platform_y):
            return None  # it would land on itself
        platform = self._platform_under(mirror_x, mirror_feet)
        return (mirror_x, platform) if platform is not None else None

    def _mirror_platform(self, index):
        """The index of the platform that is index's mirror image, or None."""
        return self._mirror_index("platforms", index)

    def _mirror_decoration(self, index):
        """The index of the decoration that is index's mirror image, or None."""
        return self._mirror_index("decorations", index)

    def _mirror_index(self, kind, index):
        """The index of the box in level[kind] that is the mirror image of box index, or None."""
        box = self.level[kind][index]
        mirrored = self._mirror_box(box["x"], box["y"], box["width"], box["height"])
        if mirrored is None:
            return None
        wanted = dict(box, x=mirrored[0], y=mirrored[1])
        for other, candidate in enumerate(self.level[kind]):
            if other != index and candidate == wanted:
                return other
        return None

    def _mirror_enemy(self, index):
        """The index of the enemy that is index's mirror image, or None."""
        enemy = self.level["enemies"][index]
        x, y, size, _ = self._enemy_rect(index)
        mirrored = self._mirror_box(x, y, size, size)
        if mirrored is None:
            return None
        for other in range(len(self.level["enemies"])):
            other_x, other_y, _, _ = self._enemy_rect(other)
            if (other != index and self.level["enemies"][other]["kind"] == enemy["kind"]
                    and abs(other_x - mirrored[0]) < 0.5 and abs(other_y - mirrored[1]) < 0.5):
                return other
        return None

    # ------------------------------------------------------------------
    # Watching data/level.json for changes made outside the game
    # ------------------------------------------------------------------

    def _watch_file(self, dt):
        self.file_check_left -= dt
        if self.file_check_left > 0:
            return
        self.file_check_left = FILE_CHECK_SECONDS
        file_time = self._file_time()
        if file_time == self.file_time:
            return
        self.file_time = file_time
        try:
            level = load_level(self.game.session.level_file)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # Probably saved halfway through an edit; keep the old level.
            self.game.show_notice(f"level.json not loaded: {error}")
            return
        self.game.session.set_level(level)
        self.game.show_notice(f"Reloaded data/{self.game.session.level_file}")

    def _file_time(self):
        try:
            return os.path.getmtime(level_path(self.game.session.level_file))
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Finding things in the level
    # ------------------------------------------------------------------

    @property
    def level(self):
        return self.game.session.level

    def _camera_y(self):
        session = self.game.session
        return session.camera_y.get(session.my_team, 0.0)

    def _mouse(self):
        """The mouse position in the level (the screen position plus the camera)."""
        x, y = self.game.mouse_position()
        return x + self.game.session.scroll_x, y + self._camera_y()

    def _copy_level(self):
        # A deep copy, so the level everyone is playing isn't changed until _apply().
        return copy.deepcopy(self.level)

    def _snap(self, value):
        """Round to the nearest half block, so things line up easily. While
        ALT is held, only to the nearest whole pixel (exactly at the mouse)."""
        if is_key_down(KeyboardKey.KEY_LEFT_ALT) or is_key_down(KeyboardKey.KEY_RIGHT_ALT):
            return round(value)
        step = self.game.settings["world"]["block_size"] / 2
        snapped = round(value / step) * step
        # 200 instead of 200.0, so level.json stays tidy.
        return int(snapped) if float(snapped).is_integer() else snapped

    def _platform_rect(self, start_x, start_y, mouse_x, mouse_y):
        """The platform a drag from (start_x, start_y) to the mouse would make.
        At least half a block in each direction, so a click still makes one."""
        step = self.game.settings["world"]["block_size"] / 2
        end_x, end_y = self._snap(mouse_x), self._snap(mouse_y)
        x, y = min(start_x, end_x), min(start_y, end_y)
        return x, y, max(abs(end_x - start_x), step), max(abs(end_y - start_y), step)

    def _moved_rect(self, mouse_x, mouse_y):
        """Where the thing being moved would end up: (x, y, width, height)."""
        what, index, offset_x, offset_y, _ = self.moving
        if what in ("platform", "decoration"):
            platform = self.level[what + "s"][index]
            return (self._snap(mouse_x - offset_x), self._snap(mouse_y - offset_y),
                    platform["width"], platform["height"])
        if what == "flag":
            _, _, width, height = flag_rect(self.level["flag"], self.game.settings)
            return self._snap(mouse_x - offset_x), self._snap(mouse_y - offset_y), width, height
        size = self.game.settings["enemy"]["size"]
        platform = self._platform_under(mouse_x, mouse_y)
        top = self.level["platforms"][platform]["y"] if platform is not None else mouse_y
        return self._snap(mouse_x) - size / 2, top - size, size, size

    def _enemy_rect(self, index):
        """Where enemy number index starts: (x, y, size, size)."""
        enemy = self.level["enemies"][index]
        size = self.game.settings["enemy"]["size"]
        top = self.level["platforms"][enemy["platform"]]["y"]
        return enemy["x"] - size / 2, top - size, size, size

    def _enemy_at(self, x, y):
        for index in reversed(range(len(self.level["enemies"]))):
            if _inside(x, y, *self._enemy_rect(index)):
                return index
        return None

    def _flag_at(self, x, y):
        flag = self.level["flag"]
        return flag is not None and _inside(x, y, *flag_rect(flag, self.game.settings))

    def _pit_at(self, x, y):
        """Runner levels: the index of the pit under the mouse (clicking in the
        gap, at or below the ground's top), or None."""
        if self.level["mode"] != RUNNER:
            return None
        world = self.game.settings["world"]
        if y < world["height"] - world["ground_height"]:
            return None
        for index, pit in enumerate(self.level["pits"]):
            if pit["x"] <= x <= pit["x"] + pit["width"]:
                return index
        return None

    def _decoration_picked(self, x, y):
        """The decoration a click at (x, y) means, or None. If a platform is
        also there, the platform wins unless the decoration tool is selected."""
        decorations = self.level["decorations"]
        for index in reversed(range(len(decorations))):
            d = decorations[index]
            if _inside(x, y, d["x"], d["y"], d["width"], d["height"]):
                if self.tool == "decoration" or self._platform_at(x, y) is None:
                    return index
                return None
        return None

    def _platform_at(self, x, y):
        """The index of the platform under the mouse (the newest, if they overlap), or None."""
        platforms = self.level["platforms"]
        for index in reversed(range(len(platforms))):
            p = platforms[index]
            if _inside(x, y, p["x"], p["y"], p["width"], p["height"]):
                return index
        return None

    def _platform_under(self, x, y):
        """The platform something clicked at (x, y) would stand on: the
        highest one at or below the mouse, within a block. None if there isn't one."""
        reach = self.game.settings["world"]["block_size"]
        best = None
        for index, p in enumerate(self.level["platforms"]):
            if p["x"] <= x <= p["x"] + p["width"] and p["y"] - reach <= y <= p["y"] + p["height"]:
                if best is None or p["y"] < self.level["platforms"][best]["y"]:
                    best = index
        return best

    # ------------------------------------------------------------------
    # The help panel
    # ------------------------------------------------------------------

    def _draw_help(self):
        lines = ["EDIT MODE  (E to leave)"]
        for number, tool in enumerate(TOOLS.values(), start=1):
            marker = ">" if tool == self.tool else " "
            lines.append(f"{marker} {number}  {tool}")
        if self.level["mode"] == RUNNER:
            lines += ["Arrows / wheel: scroll", "  (SHIFT faster, HOME = start)"]
        lines += ["Left: place / drag a platform", "Ctrl + drag: move", "Right-click: delete",
                  "ALT: no snapping",
                  f"M: mirror mode ({'ON' if self.mirror else 'off'})",
                  f"F: fly mode ({'ON' if self.game.session.is_flying() else 'off'})"]

        font_size = 18
        line_height = 22
        x, y = 20, 130
        width = max(measure_text(line, font_size) for line in lines) + 20
        draw_rectangle(x - 10, y - 10, width, len(lines) * line_height + 14, PANEL_COLOR)
        for number, line in enumerate(lines):
            color = PREVIEW_COLOR if line.startswith(">") or "ON" in line else TEXT_COLOR
            draw_text(line, x, y + number * line_height, font_size, color)


def _inside(px, py, x, y, width, height):
    return x <= px <= x + width and y <= py <= y + height
