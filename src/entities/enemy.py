"""Enemies and their AI.

An enemy lives on one platform from data/level.json. What it does is
decided by a state machine (the same StateMachine class the game uses for
its screens) with two states and two transitions:

    PATROL --(a player lands on the enemy's platform)----------------> CHASE
    CHASE  --(the target has left the platform and no one else is on it)--> PATROL

PATROL  Walks to one end of the platform, turns round and walks to the
        other end, forever (scripted waypoints: the two platform ends).
CHASE   Steers toward the target player along the platform ("seek"
        steering): it accelerates toward the player instead of instantly
        matching their position, so it turns round with a bit of momentum and
        a player can jump over it. As it gets close it brakes and stops right
        under the player ("arrive") instead of overshooting and swinging back.

Why this movement: the enemy only ever moves left and right along one flat
platform, so there is nothing to find a path around; pathfinding (A*) would
add nothing. Walking between the two ends is predictable, like a Koopa in
Mario, so players can learn its timing. Seek steering makes the chase react
to the player while speeding up and slowing down like the players' own
physics (it uses the same approach() helper). Both movements are clamped to
the platform's ends, so the enemy never walks off.

Touching the enemy (its square overlapping a player's hitbox, in either
state) sends the whole game back to the start: GameServer respawns every
player and resets every enemy. Jumping over it is the way past.

Only the host runs this (GameServer). Clients just draw each enemy where the
host's snapshots say it is, colored by its state.
"""

from dataclasses import dataclass

from core.state_machine import StateMachine
from entities.physics import approach

PATROL = "patrol"
CHASE = "chase"
STATES = (PATROL, CHASE)  # snapshots send the state as its index in this tuple


@dataclass
class Enemy:
    id: int
    platform: int | None  # index of the platform it lives on (None on clients)
    x: float = 0.0  # top-left corner
    y: float = 0.0
    size: float = 40.0  # it's a square for now
    vx: float = 0.0  # pixels per second; positive is right
    direction: int = 1  # 1 = moving/facing right, -1 = left
    state: str = PATROL  # name of the current AI state (sent to clients)


class EnemyState:
    """Base class for an enemy AI state. StateMachine calls enter/exit/update."""

    name = ""

    def __init__(self, brain):
        self.brain = brain

    def enter(self):
        # Record the state's name on the enemy so snapshots can send it.
        self.brain.enemy.state = self.name

    def exit(self):
        pass

    def update(self, dt):
        pass


class PatrolState(EnemyState):
    name = PATROL

    def update(self, dt):
        brain = self.brain
        enemy = brain.enemy

        # Transition: a player has landed on my platform -> chase them.
        target = brain.player_on_platform()
        if target is not None:
            brain.machine.change(ChaseState(brain, target.id))
            return

        # Movement: walk at a steady speed; at an end of the platform, turn round.
        enemy.vx = enemy.direction * brain.tuning["patrol_speed"]
        hit_end = brain.move(dt)
        if hit_end != 0:
            enemy.direction = -hit_end  # hit the left end (-1) -> walk right (1), and vice versa


class ChaseState(EnemyState):
    name = CHASE

    def __init__(self, brain, target_id):
        super().__init__(brain)
        self.target_id = target_id

    def update(self, dt):
        brain = self.brain
        enemy = brain.enemy
        tuning = brain.tuning

        target = brain.players.get(self.target_id)
        if target is None or not brain.is_on_or_above_platform(target):
            # The target fell off, walked off or left the game. Switch to
            # anyone else standing on the platform; if there's no one,
            # transition back to patrolling.
            target = brain.player_on_platform()
            if target is None:
                brain.machine.change(PatrolState(brain))
                return
            self.target_id = target.id

        # Movement (seek steering): work out the speed we want, then let
        # approach() change our speed toward it by at most chase_acceleration
        # per second, so turning round takes a moment.
        target_center = target.x + brain.player_width / 2
        offset = target_center - (enemy.x + enemy.size / 2)
        distance = abs(offset)
        # "Arrive": the distance needed to brake from full speed to a stop
        # (v^2 / 2a). Inside it we want to go proportionally slower, so we
        # stop right under the target instead of overshooting and swinging back.
        braking_distance = tuning["chase_speed"] ** 2 / (2 * tuning["chase_acceleration"])
        if distance <= tuning["arrive_distance"]:
            desired_speed = 0.0  # close enough: stand still (no jittering)
        else:
            desired_speed = tuning["chase_speed"] * min(1.0, distance / braking_distance)
        desired_vx = desired_speed if offset > 0 else -desired_speed
        enemy.vx = approach(enemy.vx, desired_vx, tuning["chase_acceleration"] * dt)
        if enemy.vx != 0:
            enemy.direction = 1 if enemy.vx > 0 else -1
        brain.move(dt)


class EnemyBrain:
    """Runs one enemy's state machine on the host. The enemy starts in PATROL."""

    def __init__(self, enemy, platform, players, settings):
        self.enemy = enemy
        self.platform = platform  # {"x", "y", "width", "height"} from level.json
        self.players = players  # the server's players (only read here)
        self.settings = settings
        self.machine = StateMachine()
        self.reset()

    def reset(self):
        """Put the enemy back at its start: the middle of its platform, patrolling right."""
        enemy = self.enemy
        enemy.x = self.platform["x"] + (self.platform["width"] - enemy.size) / 2
        enemy.y = self.platform["y"] - enemy.size  # standing on top of the platform
        enemy.vx = 0.0
        enemy.direction = 1
        self.machine.change(PatrolState(self))

    @property
    def tuning(self):
        # Read from settings every time, so F5 changes the speeds live.
        return self.settings["enemy"]

    @property
    def player_width(self):
        return self.settings["player"]["width"]

    def update(self, dt):
        self.machine.update(dt)

    def move(self, dt):
        """Move by vx, stopping at the platform's ends.

        Returns -1 if the left end was hit, 1 for the right end, 0 otherwise.
        """
        enemy = self.enemy
        left_end = self.platform["x"]
        right_end = self.platform["x"] + self.platform["width"] - enemy.size
        enemy.x += enemy.vx * dt
        if enemy.x <= left_end:
            enemy.x = left_end
            enemy.vx = 0.0
            return -1
        if enemy.x >= right_end:
            enemy.x = right_end
            enemy.vx = 0.0
            return 1
        return 0

    def player_on_platform(self):
        """The in-game player standing on this enemy's platform closest to it, or None."""
        on_platform = [player for player in self.players.values()
                       if player.character is not None and player.standing_on == self.enemy.platform]
        if not on_platform:
            return None
        enemy_center = self.enemy.x + self.enemy.size / 2
        return min(on_platform, key=lambda player: abs(player.x + self.player_width / 2 - enemy_center))

    def touching_player(self):
        """An in-game player whose hitbox overlaps the enemy's square, or None."""
        enemy = self.enemy
        width = self.player_width
        height = self.settings["player"]["height"]
        for player in self.players.values():
            if player.character is None:
                continue
            if (player.x < enemy.x + enemy.size and player.x + width > enemy.x
                    and player.y < enemy.y + enemy.size and player.y + height > enemy.y):
                return player
        return None

    def is_on_or_above_platform(self, player):
        """True while the player is standing on the platform or in the air above it.

        Jumping (even right over the enemy) keeps the chase going. Walking or
        jumping off the side, or falling below the platform's top, ends it.
        """
        if player.character is None:
            return False
        center = player.x + self.player_width / 2
        above_or_on = player.y + self.settings["player"]["height"] <= self.platform["y"] + 1
        return self.platform["x"] <= center <= self.platform["x"] + self.platform["width"] and above_or_on
