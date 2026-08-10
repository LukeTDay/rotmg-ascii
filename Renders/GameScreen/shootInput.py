import curses
import math
import queue
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import Networking.PacketHelper as PacketHelper
from Constants.StatusEffects import BERSERK, DAZED
from Models.ConditionEffect import hasEffect
from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore
from Networking.Ticker import Ticker
from Renders.GameScreen.mapRenderer import screenToWorld
from Utils.json.objectNameLoader import objectRenderInfo
from Utils.json.projectileMapLoader import getProjectileDefinition, resolveShotProjectileIds

# 'f'/'F' - confirmed unused anywhere else in the app (movement/menu screens
# only claim arrows, WASD, Enter, Backspace).
_AUTOFIRE_TOGGLE_KEYS = (ord("f"), ord("F"))

# How close (world tiles) the mouse's aimed-at world position has to be to an
# enemy for the shot to snap onto it instead of firing at the raw cursor
# position - the "soft aim" behavior.
_ENEMY_SNAP_RADIUS_TILES = 1.0

# RotMG's real attack-frequency formula (attacks/ms): a DEX-based base curve
# multiplied by the equipped weapon's RateOfFire. The DEX curve was ported
# from pyrelay's Client.attackFreq and independently confirmed against
# RealmEye's documented formula (attacksPerSecond = (1.5 + 6.5*DEX/75) *
# RateOfFire - our 0.0015/0.008 attacks/ms are exactly 1.5/8.0 attacks/sec).
# DAZED clamps to the slowest DEX-based frequency (before RateOfFire is
# applied - a weapon's own inherent speed isn't a "bonus" DAZED should
# strip); BERSERK multiplies by 1.5 - same two condition flags (and the same
# Models.ConditionEffect.hasEffect check) Networking.Ticker.computeSpeed
# already uses for movement speed. RateOfFire itself (e.g. 0.55 = 55%, a slow
# staff) is per-weapon XML data threaded through ProjectileDefinition - see
# Scripts/AssetPipeline/parseGameXml.py and CLAUDE.local.md's MITM findings.
_MIN_ATTACK_FREQ = 0.0015
_MAX_ATTACK_FREQ = 0.008
_BERSERK_MULTIPLIER = 1.5

# Fallbacks used only when the equipped weapon has no ProjectileDefinition at
# all (a data gap, not expected for any real weapon - RealmEye: "All weapons
# will fire at least one projectile for each use") - still fire a single
# plain shot rather than refusing to fire.
_DEFAULT_RATE_OF_FIRE = 1.0
_DEFAULT_NUM_PROJECTILES = 1
_DEFAULT_ARC_GAP_DEGREES = 11.25

# The projectile-type-within-weapon byte (PlayerShootPacket.bulletId) -
# confirmed via real MITM capture to be sent as -1 by the actual client for
# an ordinary (single projectile type) weapon, not 0.
_DEFAULT_PROJECTILE_ID = -1


@dataclass
class AutoFireState:
    """Per-connection shoot state, created once in gameScreen.py's
    _connectedLoop alongside GameState/PlayerData/ProjectileStore and
    threaded into handleShootInput every frame - same "no hidden globals,
    explicit params" convention as the rest of this app."""

    autoFire: bool = False
    lastShotTime: int = 0
    nextShotId: int = 0
    lastMouseWorld: Optional[Tuple[float, float]] = None
    # Default facing (down) before any movement or mouse input has happened.
    lastMoveDirection: Tuple[float, float] = (0.0, 1.0)


def _attackPeriodMs(player: PlayerData, rateOfFire: float) -> float:
    if hasEffect(player.condition, DAZED):
        freq = _MIN_ATTACK_FREQ
    else:
        # player.dex is already the character's TOTAL dex (base + gear +
        # enchants all folded together by the server) - dexBoost is just the
        # informational breakdown of how much of that total is boost, not a
        # separate additive component (confirmed directly: a real character
        # with 60 base + 25 from items/enchants reported dex=85, dexBoost=25,
        # not dex=60). Adding dexBoost on top double-counts it, inflating the
        # effective ratio for every character, capped or not (e.g. dex=60,
        # dexBoost=10 -> a wrong ratio of 0.933 instead of the correct 0.8).
        # This is unlike Networking.Ticker.computeSpeed's spd+spdBoost, which
        # is confirmed (against two independent reference projects) to be a
        # genuinely separate additive pair for movement speed - the two
        # stats don't necessarily share the same combination semantics.
        #
        # DEX's contribution is NOT clamped at 75, same as SPD - confirmed by
        # live testing (2026-08-10): a character with dex well above 75 fired
        # at the correspondingly faster uncapped rate with no server-side
        # kick/disconnect, ruling out both a hard formula cap and a server-
        # side rate-limit kicking in around 75. (An earlier version of this
        # code guessed a 75 cap by analogy with other stat formulas - that
        # guess was wrong; don't reintroduce it without new evidence.)
        dexRatio = player.dex / 75
        freq = _MIN_ATTACK_FREQ + dexRatio * (_MAX_ATTACK_FREQ - _MIN_ATTACK_FREQ)
        if hasEffect(player.condition, BERSERK):
            freq *= _BERSERK_MULTIPLIER
    freq *= rateOfFire
    return 1 / freq


def _resolveAimPoint(state: GameState, mouseWorld: Tuple[float, float]) -> Tuple[float, float]:
    """The soft-aim rule: snap to the nearest enemy within
    _ENEMY_SNAP_RADIUS_TILES of the mouse's world position, if one's there;
    otherwise aim at the raw mouse position itself."""
    mouseX, mouseY = mouseWorld
    now = time.time()
    nearestPos: Optional[Tuple[float, float]] = None
    nearestDist = _ENEMY_SNAP_RADIUS_TILES
    for obj in state.objects.values():
        info = objectRenderInfo(obj.objectType)
        if info is None or not info.isEnemy:
            continue
        pos = obj.renderPos(now)
        dist = math.hypot(pos.x - mouseX, pos.y - mouseY)
        if dist <= nearestDist:
            nearestDist = dist
            nearestPos = (pos.x, pos.y)
    return nearestPos if nearestPos is not None else mouseWorld


def handleShootInput(keys: List[int], stdscr: curses.window, ticker: Ticker, player: PlayerData,
                      outgoingQueue: "queue.Queue", state: GameState, shootState: AutoFireState,
                      moveDirection: Optional[Tuple[float, float]], debugger, projectileMap,
                      projectiles: ProjectileStore) -> None:
    """Consumes this frame's already-drained keys/events (see
    movementInput.drainKeys - shared with handleMovementInput since curses'
    input buffer only yields each keystroke once, so only one caller can
    ever drain the pad itself). Two things update shootState here: the
    auto-fire toggle key, and any mouse motion/click (curses.KEY_MOUSE),
    which is converted to a world position and remembered as the aim cursor.
    `moveDirection` is this frame's resolved movement vector from
    handleMovementInput (or None) - it becomes the facing fallback used to
    aim when no mouse position is known yet (e.g. before any mouse event has
    arrived, or if this terminal doesn't report mouse motion - see
    CLAUDE.local.md's shooting plan).

    While auto-fire is on and the attack cooldown has elapsed, builds and
    enqueues one PLAYERSHOOT packet **per projectile** in the equipped
    weapon's fan (its NumProjectiles/ArcGap), not one packet per trigger-pull -
    confirmed via real MITM capture that the actual client sends a full
    separate packet per pellet (same time, incrementing bulletId, angles
    fanned symmetrically around the aim direction by ArcGap degrees), rather
    than relying on the server to fan out a single packet. `projectileMap` is
    the same dict gameScreen.py already loads via
    Utils.json.projectileMapLoader.projectileMapLoader() for incoming-shot
    rendering, reused here (via getProjectileDefinition) to look up the
    equipped weapon's own attack-cadence/fan attributes.

    `projectiles` is the same ProjectileStore gameScreen.py's _connectedLoop
    already owns and draws from - each fired shot is spawned into it directly
    here (client-side prediction), rather than relying solely on the
    server's SERVERPLAYERSHOOT broadcast echoing back to the shooter to
    trigger _spawnProjectiles the normal (reactive, other-player-shot) way.
    Whether the real server actually echoes a player's own shot back to
    themselves isn't confirmed either way (see CLAUDE.local.md's MITM
    findings) - predicting locally means our own shots always render
    immediately regardless. If an echo does arrive later, it reuses the same
    (ownerId, bulletId, shotIndex=0) key ProjectileStore already keys by, so
    it just harmlessly refreshes this same entry instead of double-spawning.
    """
    if moveDirection is not None:
        shootState.lastMoveDirection = moveDirection

    sawMouseEvent = False
    for key in keys:
        if key in _AUTOFIRE_TOGGLE_KEYS:
            shootState.autoFire = not shootState.autoFire
            # State-changing, low-frequency (a manual toggle, not a per-shot
            # event) - worth logging, unlike the per-shot packet send below.
            debugger.info(f"Auto-fire {'enabled' if shootState.autoFire else 'disabled'}")
        elif key == curses.KEY_MOUSE:
            sawMouseEvent = True

    if sawMouseEvent:
        # curses.getmouse() only ever returns the single most recently
        # dequeued mouse event, regardless of how many KEY_MOUSE entries
        # ended up in this frame's drained batch - REPORT_MOUSE_POSITION can
        # queue a KEY_MOUSE per pixel of cursor motion, so a fast mouse swipe
        # used to call this (plus computeScale() inside screenToWorld) once
        # per queued event, all but the last returning the exact same
        # (already-stale) coordinates. Doing it once per frame instead was a
        # real, noticeable frame-time regression fix, not just tidying.
        try:
            _, mouseCol, mouseRow, _, _ = curses.getmouse()
        except curses.error:
            mouseCol = mouseRow = None
        if mouseCol is not None:
            world = screenToWorld(stdscr, ticker, mouseRow, mouseCol)
            if world is not None:
                shootState.lastMouseWorld = world

    if not shootState.autoFire or ticker.pos is None:
        return
    if player.inv[0] < 0:
        # No weapon known yet (PlayerData.inv defaults every slot to -1) - or
        # genuinely empty-handed. containerType is written as an unsigned
        # short (see PlayerShootPacket), so sending -1 would raise
        # struct.error inside Sender's write loop, silently killing that
        # thread - after which no more acks go out and the server kicks the
        # client for lagging a moment later. Skip firing instead.
        return

    weaponId = player.inv[0]
    definition = getProjectileDefinition(projectileMap, weaponId, 0)
    if definition is not None:
        rateOfFire = definition.rateOfFire
        numProjectiles = max(1, definition.numProjectiles)
        arcGapRad = math.radians(definition.arcGapDegrees)
    else:
        rateOfFire = _DEFAULT_RATE_OF_FIRE
        numProjectiles = _DEFAULT_NUM_PROJECTILES
        arcGapRad = math.radians(_DEFAULT_ARC_GAP_DEGREES)

    nowMs = int(time.time() * 1000) - ticker.connectedTime
    if nowMs - shootState.lastShotTime < _attackPeriodMs(player, rateOfFire):
        return

    if shootState.lastMouseWorld is not None:
        targetX, targetY = _resolveAimPoint(state, shootState.lastMouseWorld)
    else:
        dx, dy = shootState.lastMoveDirection
        targetX, targetY = ticker.pos.x + dx, ticker.pos.y + dy
    baseAngle = math.atan2(targetY - ticker.pos.y, targetX - ticker.pos.x)

    # Fan centered symmetrically on the aim direction - for N projectiles
    # there are N-1 gaps total (RealmEye: "high tiered bows have 3
    # projectiles with an 8 degree arc gap, meaning the two gaps between the
    # three projectiles are at 8 degrees"), confirmed to match a real 4-
    # projectile staff capture's angles exactly.
    #
    # Not every shot in the fan uses the same projectile type: tiered bows
    # (and similar weapons) fire a stronger center shot and weaker side
    # shots, defined as two separate <Projectile> blocks on the same weapon -
    # resolveShotProjectileIds derives which id each shot index actually
    # uses (see its docstring). The wire packet's own bulletId byte still
    # always sends _DEFAULT_PROJECTILE_ID regardless - that field is
    # confirmed -1 on real captures independent of which internal projectile
    # type is involved; only our *local* prediction's speed/damage/visual
    # needs the per-shot-resolved definition.
    shotProjectileIds = resolveShotProjectileIds(projectileMap, weaponId, numProjectiles)
    shotPos = ticker.pos.clone()
    playerPos = ticker.pos.clone()
    for i in range(numProjectiles):
        angle = baseAngle + (i - (numProjectiles - 1) / 2) * arcGapRad

        packet = PacketHelper.createPacket("PLAYERSHOOT")
        packet.time = nowMs
        packet.shotId = shootState.nextShotId
        packet.containerType = weaponId
        packet.bulletId = _DEFAULT_PROJECTILE_ID
        packet.shotPos = shotPos
        packet.angle = angle
        packet.burstId = 0  # a distinct, hardcoded-cooldown weapon mechanic - not implemented, see CLAUDE.local.md
        packet.pos = playerPos
        outgoingQueue.put(packet)

        shotDefinition = getProjectileDefinition(projectileMap, weaponId, shotProjectileIds[i]) or definition
        if shotDefinition is not None:
            projectiles.spawn(
                bulletId=shootState.nextShotId,
                ownerId=player.objectId,
                startingPos=shotPos,
                angle=angle,
                speed=shotDefinition.speed,
                damage=shotDefinition.damage,
                lifetimeMS=shotDefinition.lifetimeMS,
                size=shotDefinition.size,
                visualObjectType=shotDefinition.visualObjectType,
            )

        shootState.nextShotId = (shootState.nextShotId + 1) % 128

    shootState.lastShotTime = nowMs
