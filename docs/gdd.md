# [TempName] — Game Design Document

Have not thought of game name yet  
 
**Student Name:** Suhrab Roeen  
**Student ID:** 100811513  
**Date:** September 21, 2026  
**Class:** CSCI 4160U Game Development  
**Repository:** [Suhrab-R/gamedev-final-project](https://github.com/Suhrab-R/gamedev-final-project)

---

## Description

**Description:**
Temp is a 2D local-network multiplayer game built with raylib (Python bindings), with plans to be played together live with the whole class. Every connected classmate's laptop joins over the same Wi-Fi/LAN, with one laptop acting as host/server, and players are randomly split into two teams. The teams then race and fight through three back-to-back stages:

1. **Vertical platformer race** — both teams climb a shared tower, separated at first by a center wall that ends partway through to allow teams to sabotage, solving switch/button puzzles together to make progress.
2. **Endless-runner sprint** — a Jetpack Joyride-style dodge run in separated lanes that also ends partway through, putting all players in one big playspace.
3. **Boss gauntlet** — each team fights its own mini-boss in a separate arena, then the walls drop and both teams face one shared final boss, free to cooperate or sabotage each other.

Whichever team wins 2 of the 3 stages wins the match. The whole thing is scoped to run inside a single class period, with a player count that can scale up or down depending on how many classmates want to play.

## Core Gameplay Loop

### The Gameplay Loop

1. Connected players are randomly split into Team A / Team B.
2. **Stage 1 (Platformer Race):** both teams climb their half of the tower divided by a center wall, using switches/buttons to open paths, until the separation wall ends and allows players to reach each other; the first team to get 2+ living members to the top wins the stage.
3. **Stage 2 (Endless Runner):** teams run in separate lanes, dodging obstacles at increasing speed, until the separation wall ends; whichever team gets 1 living member to the finish line first wins the stage.
4. **Stage 3 (Boss Gauntlet):** each team fights its own mini-boss in a separate arena; once both mini-bosses are down (or a timer forces it), the arena opens into one shared final boss, and teams can cooperate or sabotage each other to win it. Team with more players alive wins.
5. Whichever team won 2 of the 3 stages is declared the match winner; results show on a scoreboard, and (time-permitting) the class can reshuffle teams and play again.

### Primary Mechanics

- Move (left/right), jump and duck
- Pick up and throw items and players (think *New Super Mario Bros. Wii*)
- Interact with switches/buttons/levers to open paths for your team
- Fall/die → lose a life
- Dodge incoming obstacles at increasing speed
- Dodge and attack boss patterns

### Secondary Mechanics

- Lives and respawn management — each player tracks remaining lives; at 0 they're out for that stage and can only spectate until the team advances or restarts.
- Section completion thresholds — Stage 1 needs 2+ living teammates at the top or the team restarts from the bottom; Stage 2 needs only 1 living teammate to finish.
- Wall/barrier end — a section of the level opening the two teams to each other partway through each stage.
- Sabotage actions — direct interference between opposing players once the separation ends: throwing items that slow or push other players, picking up and throwing other players, etc.
- Section scoreboard — tracks which team won each of the 3 stages toward the 2-of-3 match result.

### Tertiary Mechanics

- Team-color cosmetics/visual identifiers, so players can tell teammates from opponents at a glance.
- Environmental hazard variety per stage (moving platforms, spikes, timed gates in Stage 1; new obstacle types as Stage 2 speeds up).
- Pickup items that can be used to sabotage players on the other team (maybe buffs for your own team could be added).

## MDA Framework

### Mechanics

Player movement/physics, an individual-lives counter per player, switch/trigger objects that unlock paths, a wall/barrier object that ends at a certain progress level, obstacle-spawning logic with increasing speed for Stage 2, boss state machines with defined attack patterns and health, a section-completion checker (2-alive-minimum for Stage 1, 1-alive-minimum for Stage 2), and a match-level scoreboard tallying stage wins.

### Dynamics

Teammates calling out switch locations and coordinating who pushes ahead versus who plays it safe; visible tension as a team's remaining-lives count gets low and players start playing more cautiously; a rush of aggression the moment the wall ends and sabotage becomes possible; teams settling into an informal "send one runner" strategy for Stage 2 once they realize only one survivor is needed; and, in the final boss, a live in-the-moment decision for each team about whether cooperating gets the boss down faster than fighting the other team for the kill.

### Aesthetics

Competitive chaos and spectacle (this is a live demo — it should read clearly and be fun to watch from the sidelines, not just to play), team fellowship under pressure, and a satisfying escalation from careful platforming, to frantic dodging, to boss-fight spectacle as the match builds toward its climax.

## Player Experience

### How should they feel? (LeBlanc's Taxonomy)

Primarily **Challenge** (platforming, dodging, and boss patterns all ask players to beat a difficulty curve) and **Fellowship** (the whole design is built around a team needing each other — the 2-alive and 1-alive thresholds specifically force cooperation). There's a secondary layer of **Sensation** in Stage 2's speed-up and the Stage 3 boss spectacle.

### Game Inspirations

- *Jetpack Joyride*
- *New Super Mario Bros. Wii*
- *Only Up*
- *Fireboy and Watergirl*

### Non-Game Inspirations

- Team-based reality/competition shows (e.g. *Wipeout*, *American Ninja Warrior*) — escalating skill challenges with eliminations, building to a head-to-head finale.

### Genre

Local-network multiplayer, team-competitive action-platformer, structured as a 3-stage gauntlet (platformer race → endless runner → boss fight) with a party-game framing.

### Target Audience (Bartle's Taxonomy)

The main audience is the class during the presentation of the game, but in Bartle's terms the design leans hardest on **Achievers** (each stage is a concrete goal — reach the top, reach the finish line, beat the boss) and **Griefers** (the sabotage window and team-vs-team framing give players a direct way to compete with each other, not just the level).

### Progression Over Time

This is a single-session, single-match game with no persistent meta-progression (no unlocks, no save file) — built to be explained and played once, live, in one class period. Within a match, difficulty escalates stage to stage: Stage 1 is deliberately slower and puzzle-focused, Stage 2 speeds up progressively, and Stage 3 is the highest-intensity boss spectacle. If time allows, the class could reshuffle teams and replay.

### Themes

Still to be decided.

### Platform & Tools

- **Engine/library:** raylib, via a Python binding.
- **Expected scale:** ~13 concurrent players.
- **Networking:** LAN-based client-server over university Wi-Fi — host laptop as server, student laptops as clients. At ~13 players, a lightweight custom protocol over Python's `socket` module is more practical than a general-purpose networking library: UDP for frequent state (position, input, sent at a fixed tick rate like 20 Hz rather than every frame), TCP (or a small reliable layer on top of UDP) for one-off events that can't be dropped — switch triggers, scoring, stage transitions.
- **Platform:** desktop (Windows/macOS/Linux, whatever the classroom laptops run).
- **Input:** each connected player uses their own laptop's keyboard, sent to the host over the network.

### Anything else unusual that needs explaining (if applicable)

*Not yet filled in.*
