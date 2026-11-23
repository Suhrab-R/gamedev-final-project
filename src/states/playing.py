"""State 2: in the game, running and jumping with the other players.

Each frame the held keys go to the host (straight into the server on the
host's own computer, over UDP from a client). Every player is drawn where
the host says they are: on the host that is the server's own data, on a
client it is the newest snapshot.

The host also gets the level editor (editor/level_editor.py, E to toggle).
"""

from pyray import *

from core.level import CHASER, RUNNER, all_platforms, flag_rect, in_view
from core.state_machine import GameState
from editor.level_editor import LevelEditor
from entities import animation
from entities.enemy import CHASE
from entities.player import TEAMS, hitbox_size
from ui.draw import (
    BACKGROUND_COLOR, MUTED_TEXT_COLOR, TEAM_COLORS, TEXT_COLOR,
    draw_banner, draw_disconnected_overlay, draw_enemy, draw_level, draw_progress_bar, draw_runner_progress_bar,
    draw_text_centered,
)

# Show a hint if no positions have arrived after this many seconds.
NO_DATA_WARNING_SECONDS = 2.0
# How big the life icons (our character's idle sprite) are, in screen pixels per sprite pixel.
LIFE_ICON_SCALE = 1.5
# How fast a player who just respawned (invulnerable) blinks.
BLINKS_PER_SECOND = 5
# The progress bar leaves this fraction of the screen empty at each end
# (of its height in climb levels, its width in runner levels).
PROGRESS_BAR_MARGIN = 0.15


def read_axis(negative_key, positive_key, last_pressed):
    """Return (value, last_pressed) for one axis made of two opposite keys.

    value is -1, 0 or 1. If both keys are held, the one pressed most recently
    wins (instead of them cancelling out to 0), so holding D and then also
    pressing A turns you around. last_pressed (-1 or 1) remembers which key
    went down last; pass back the returned one next frame.
    """
    if is_key_pressed(negative_key):
        last_pressed = -1
    if is_key_pressed(positive_key):
        last_pressed = 1

    negative_held = is_key_down(negative_key)
    positive_held = is_key_down(positive_key)
    if negative_held and positive_held:
        return last_pressed, last_pressed
    if negative_held:
        return -1, last_pressed
    if positive_held:
        return 1, last_pressed
    return 0, last_pressed


class PlayingState(GameState):
    def enter(self):
        self.time_in_state = 0.0
        # Which key of each direction pair (A/D, W/S) was pressed most recently.
        self.last_pressed_x = 1
        self.last_pressed_y = 1
        # player id -> the jump_count we last played a jump sound for.
        self.heard_jump_counts = {}
        # Only the host can edit the level (it's the one that owns it).
        me = self.game.my_player()
        self.editor = LevelEditor(self.game) if me is not None and me.is_host else None

    def update(self, dt):
        self.time_in_state += dt
        # Send this frame's keys. The host moves us; we just draw the result.
        self.game.session.send_input(*self._read_input())
        if self.editor is not None:
            self.editor.update(dt)
        self._play_jump_sounds()
        for player in self.game.session.players.values():
            animation.advance(player, dt)

    def _play_jump_sounds(self):
        """Play the jump sound for every player whose jump count changed.

        Jumps happen on the host, so a client can't see them directly; the
        host counts each player's jumps and sends the count in snapshots.
        If a snapshot is lost the next one still has the new count, so the
        sound isn't lost with it.
        """
        for player in self.game.session.players.values():
            if player.character is None:
                continue
            heard = self.heard_jump_counts.get(player.id)
            if heard is not None and heard != player.jump_count:
                self.game.assets.play("jump")
            # First time we see a player, just remember their count (no sound).
            self.heard_jump_counts[player.id] = player.jump_count

    def _read_input(self):
        """Return (input_x, input_y, jump_held, run_held) for the keys held right now.

        WASD gives the direction (-1, 0 or 1 on each axis), SPACE is jump and
        either SHIFT is run.
        """
        input_x, self.last_pressed_x = read_axis(KeyboardKey.KEY_A, KeyboardKey.KEY_D, self.last_pressed_x)
        input_y, self.last_pressed_y = read_axis(KeyboardKey.KEY_W, KeyboardKey.KEY_S, self.last_pressed_y)
        jump_held = is_key_down(KeyboardKey.KEY_SPACE)
        run_held = is_key_down(KeyboardKey.KEY_LEFT_SHIFT) or is_key_down(KeyboardKey.KEY_RIGHT_SHIFT)
        return input_x, input_y, jump_held, run_held

    def render(self):
        game = self.game
        session = game.session
        clear_background(BACKGROUND_COLOR)

        # The world is drawn through cameras: something at world (x, y)
        # appears on screen at (x - camera x, y - camera y). camera_y is our
        # team's own (climb levels; always 0 in runner levels). The level
        # also moves left by scroll_x: in runner levels the obstacles slide
        # past a still screen, while the players stay in screen positions.
        level_camera = Camera2D(Vector2(0, 0), Vector2(session.scroll_x, self.camera_y()), 0, 1)
        player_camera = Camera2D(Vector2(0, 0), Vector2(0, self.camera_y()), 0, 1)

        begin_mode_2d(level_camera)
        if self.editor is not None:
            self.editor.render_background()
        level = session.level
        flag_area = flag_rect(level["flag"], game.settings) if level["flag"] is not None else None
        # Only draw what's in our view, not the whole level.
        def on_screen(item):
            return in_view(item["x"], item["y"], item["width"], item["height"],
                           session.scroll_x, self.camera_y(), game.screen_width, game.screen_height)
        world = game.settings["world"]
        platforms = [p for p in all_platforms(level, world) if on_screen(p)]
        decorations = [d for d in level["decorations"] if on_screen(d)]
        draw_level(world, platforms, decorations, flag_area, session.scroll_x,
                   ground_strip=level["mode"] != RUNNER)
        end_mode_2d()

        begin_mode_2d(player_camera)
        self._draw_enemies()
        self._draw_players()
        end_mode_2d()

        if self.editor is not None:
            begin_mode_2d(level_camera)
            self.editor.render_world()
            end_mode_2d()

        # Everything below stays put on the screen.
        self._draw_progress()
        self._draw_hud()
        if self.editor is not None:
            self.editor.render()

        if session.completed_by_id is not None:
            self._draw_level_complete()

        if not session.has_positions and self.time_in_state > NO_DATA_WARNING_SECONDS:
            draw_text_centered("Waiting for game data from the host (is UDP blocked by a firewall?)",
                               game.screen_width / 2, game.screen_height / 2, 24, TEXT_COLOR)

        if session.disconnect_reason:
            draw_disconnected_overlay(session.disconnect_reason, game.screen_width, game.screen_height)

    def camera_y(self):
        """Our team's camera height (the world y at the top of the screen)."""
        return self.game.session.camera_y.get(self.game.session.my_team, 0.0)

    def _draw_progress(self):
        """The progress tracker in the middle of the screen. Climb levels: how
        far each team's highest player has climbed from the ground to the
        flag. Runner levels: how far the screen has scrolled along the course,
        the same for both teams (they dodge the same obstacles)."""
        game = self.game
        level = game.session.level
        if level["mode"] == RUNNER:
            # Lying along the middle floor, from left to right, with gaps at the ends.
            length = level["length"]
            progress = min(game.session.scroll_x / length, 1.0) if length > 0 else 1.0
            split = level["split"]
            margin = game.screen_width * PROGRESS_BAR_MARGIN
            draw_runner_progress_bar(margin, game.screen_width - margin, split["y"], split["height"], progress)
            return

        margin = game.screen_height * PROGRESS_BAR_MARGIN  # gaps above and below the bar
        flag = level["flag"]
        if flag is None:
            return  # nothing to make progress toward
        world = game.settings["world"]
        _, height = hitbox_size(game.settings)
        start = world["height"] - world["ground_height"]  # feet on the ground = 0%
        _, flag_y, _, flag_height = flag_rect(flag, game.settings)
        goal = flag_y + flag_height  # feet at the bottom of the flag = 100%
        if goal >= start:
            return  # the flag is at (or below) ground level; there's no climb to show

        progress_by_team = {team: None for team in TEAMS}
        for player in game.session.players.values():
            if not player.in_play:
                continue
            progress = (start - (player.y + height)) / (start - goal)
            progress = min(max(progress, 0.0), 1.0)
            best = progress_by_team[player.team]
            if best is None or progress > best:
                progress_by_team[player.team] = progress

        draw_progress_bar(game.screen_width / 2, margin, game.screen_height - margin, progress_by_team)

    def _draw_enemies(self):
        """Regular Goombas look normal; chasers have marks above their head,
        and their eyes turn red while they chase someone."""
        game = self.game
        size = game.settings["enemy"]["size"]
        scale = game.settings["enemy"]["scale"]  # sprite pixels -> screen pixels, like the players' scale
        for enemy in game.session.enemies.values():
            if enemy.kind == CHASER:
                sprite = "chaser_chasing" if enemy.state == CHASE else "chaser"
            else:
                sprite = "regular"
            draw_enemy(enemy, size, game.assets.enemy_texture(sprite), scale)

    def _draw_level_complete(self):
        game = self.game
        session = game.session
        who = "You" if session.completed_by_id == session.my_id else f"P{session.completed_by_id}"
        draw_banner("LEVEL COMPLETE!", f"{who} reached the flag. Back to the start in a moment...",
                    TEAM_COLORS[session.completed_team], game.screen_width, game.screen_height)

    def _draw_players(self):
        game = self.game
        my_id = game.session.my_id
        width, height = hitbox_size(game.settings)
        walk_frame_distance = game.settings["animation"]["walk_frame_distance"]

        others = []
        me = None
        for player in game.session.players.values():
            if not player.in_play:
                continue  # still choosing a character, or out of lives
            if player.id == my_id:
                me = player
            else:
                others.append(player)

        # Draw ourselves last so we are always on top.
        if me is not None:
            others.append(me)

        for player in others:
            frame = animation.frame_name(player, walk_frame_distance)
            tint = WHITE
            if player.invulnerable:
                # Just respawned: blink between solid and faint, 5 times a second.
                if int(get_time() * BLINKS_PER_SECOND * 2) % 2 == 1:
                    tint = Color(255, 255, 255, 70)
            game.draw_player_character(player.character, player.x, player.y,
                                       width, height, player.team, player.facing, frame=frame, tint=tint)

            label = "YOU" if player.id == my_id else f"P{player.id}"
            if player.is_host:
                label += " (HOST)"
            # Team-colored, since sprite characters look the same on both teams.
            draw_text_centered(label, player.x + width / 2, player.y - 22, 16, TEAM_COLORS[player.team])

    def _draw_hud(self):
        game = self.game
        session = game.session
        draw_text(f"TEAM {session.my_team.upper()}", 20, 20, 28, TEAM_COLORS[session.my_team])
        draw_text(f"Players online: {len(session.players)}", 20, 56, 20, TEXT_COLOR)
        me = game.my_player()
        if me is not None and me.is_host:
            draw_text(f"Hosting on {session.lan_ip}", 20, 84, 20, MUTED_TEXT_COLOR)
        draw_text_centered("A / D to move,  SHIFT to run,  SPACE to jump (hold for higher)",
                           game.screen_width / 2, 20, 20, MUTED_TEXT_COLOR)
        if me is not None and me.character is not None:
            self._draw_lives(me)

    def _draw_lives(self, me):
        """Our lives in the top-right corner: one small picture of our
        character per life left, or a message once we're out."""
        game = self.game
        if me.lives <= 0:
            # On a dark box, so it's readable over whatever is behind it.
            box_width, box_height = 560, 96
            top = game.screen_height - 160
            draw_rectangle(int(game.screen_width / 2 - box_width / 2), top, box_width, box_height, Color(20, 20, 28, 210))
            draw_text_centered("OUT OF LIVES", game.screen_width / 2, top + 14, 40, RAYWHITE)
            draw_text_centered("Watching the others until the level starts over",
                               game.screen_width / 2, top + 62, 20, LIGHTGRAY)
            return
        texture = game.assets.character_texture(me.character, me.team)
        right = game.screen_width - 20
        draw_text("LIVES", right - measure_text("LIVES", 20), 20, 20, TEXT_COLOR)
        if texture is None:  # no sprite: just the number
            draw_text(str(me.lives), right - measure_text(str(me.lives), 28), 46, 28, TEAM_COLORS[me.team])
            return
        icon_width = texture.width * LIFE_ICON_SCALE
        for number in range(me.lives):
            x = right - (number + 1) * (icon_width + 6) + 6
            draw_texture_ex(texture, Vector2(x, 48), 0, LIFE_ICON_SCALE, WHITE)
