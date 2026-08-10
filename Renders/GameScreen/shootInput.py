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

# Confirmed unused elsewhere in the app.
_AUTOFIRE_TOGGLE_KEYS = (ord("f"), ord("F"))

# Soft-aim snap radius, in world tiles.
_ENEMY_SNAP_RADIUS_TILES = 1.0

# RotMG's DEX-based attack-frequency formula (attacks/ms), confirmed against
# RealmEye's docs. DAZED clamps to _MIN before RateOfFire; BERSERK is a 1.5x
# multiplier after.
_MIN_ATTACK_FREQ = 0.0015
_MAX_ATTACK_FREQ = 0.008
_BERSERK_MULTIPLIER = 1.5

# Used only if the weapon has no ProjectileDefinition at all - still fires a
# plain single shot instead of refusing.
_DEFAULT_RATE_OF_FIRE = 1.0
_DEFAULT_NUM_PROJECTILES = 1
_DEFAULT_ARC_GAP_DEGREES = 11.25

# Confirmed via MITM: real client sends -1 here for a single-projectile weapon.
_DEFAULT_PROJECTILE_ID = -1


@dataclass
class AutoFireState:
    """Per-connection shoot state, threaded into handleShootInput each frame."""

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
        # player.dex is already base+gear+enchants combined - adding dexBoost
        # on top would double-count it. Not clamped at 75 (confirmed live:
        # uncapped dex fires at the uncapped rate, no server kick).
        dexRatio = player.dex / 75
        freq = _MIN_ATTACK_FREQ + dexRatio * (_MAX_ATTACK_FREQ - _MIN_ATTACK_FREQ)
        if hasEffect(player.condition, BERSERK):
            freq *= _BERSERK_MULTIPLIER
    freq *= rateOfFire
    return 1 / freq


def _resolveAimPoint(state: GameState, mouseWorld: Tuple[float, float]) -> Tuple[float, float]:
    """Snaps to the nearest enemy within _ENEMY_SNAP_RADIUS_TILES, else the raw mouse position."""
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
                      projectiles: ProjectileStore,
                      mouseEvent: Optional[Tuple[int, int, int]]) -> None:
    """Consumes this frame's already-drained keys (see movementInput.drainKeys
    - shared since curses only yields each keystroke once) and `mouseEvent`
    (movementInput.getFrameMouseEvent's single per-frame fetch, also shared
    with panelInput.handlePanelInput - never call curses.getmouse() here
    directly). Toggles auto-fire, tracks mouse aim, and while firing sends
    one PLAYERSHOOT packet per projectile in the weapon's fan (confirmed via
    MITM - not one per trigger pull). Spawns each shot into `projectiles`
    immediately (client-side prediction) rather than waiting on the server's
    echo; a later echo reuses the same (ownerId, bulletId, shotIndex) key,
    so it just refreshes the entry instead of double-spawning.
    """
    if moveDirection is not None:
        shootState.lastMoveDirection = moveDirection

    for key in keys:
        if key in _AUTOFIRE_TOGGLE_KEYS:
            shootState.autoFire = not shootState.autoFire
            # State-changing, low-frequency (a manual toggle, not a per-shot
            # event) - worth logging, unlike the per-shot packet send below.
            debugger.info(f"Auto-fire {'enabled' if shootState.autoFire else 'disabled'}")

    if mouseEvent is not None:
        mouseRow, mouseCol, _bstate = mouseEvent
        world = screenToWorld(stdscr, ticker, mouseRow, mouseCol)
        if world is not None:
            shootState.lastMouseWorld = world

    if not shootState.autoFire or ticker.pos is None:
        return
    if player.inv[0] < 0:
        # No weapon (or unknown yet) - containerType is an unsigned short, so
        # sending -1 would raise inside Sender's write loop and kill that thread.
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

    # Fan centered on the aim direction, N-1 gaps for N projectiles - confirmed
    # against a real 4-projectile staff capture. Not every shot uses the same
    # projectile type (see resolveShotProjectileIds); the wire packet's
    # bulletId is still always _DEFAULT_PROJECTILE_ID regardless - only our
    # local prediction needs the per-shot definition.
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
        packet.burstId = 0  # separate weapon mechanic, not implemented
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
