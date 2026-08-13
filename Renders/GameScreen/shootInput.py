import curses
import math
import queue
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import Networking.PacketHelper as PacketHelper
from Constants.StatusEffects import BERSERK, DAZED
from Models.ConditionEffect import hasEffect
from Models.PlayerData import PlayerData
from Models.ProjectileStore import ProjectileStore
from Networking.Ticker import Ticker
from Renders.GameScreen.inputRouter import isAutoFireToggle
from Renders.GameScreen.mapRenderer import screenToWorld
from Utils.json.projectileMapLoader import SubattackDef, getProjectileDefinition, getSubattacks, motionParams

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

# Confirmed via MITM: real client sends -1 here only for weapons with no
# <Subattack> in their XML (legacy flat-tag weapons) - see sendRealProjectileId.
_DEFAULT_PROJECTILE_ID = -1


@dataclass
class AutoFireState:
    """Per-connection shoot state, threaded into handleShootInput each frame."""

    autoFire: bool = False
    # A weapon fires every one of its Subattacks (see SubattackDef), each on
    # its own independent cooldown - keyed by that subattack's projectileId,
    # not a single weapon-wide timer.
    lastShotTimeBySubattack: Dict[int, int] = field(default_factory=dict)
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


def handleShootInput(keys: List[int], stdscr: curses.window, ticker: Ticker, player: PlayerData,
                      outgoingQueue: "queue.Queue", shootState: AutoFireState,
                      moveDirection: Optional[Tuple[float, float]], debugger, projectileMap,
                      projectiles: ProjectileStore,
                      mouseEvent: Optional[Tuple[int, int, int]],
                      keybinds: Dict[str, str]) -> None:
    """Consumes this frame's already-drained keys (see movementInput.drainKeys
    - shared since curses only yields each keystroke once) and `mouseEvent`
    (movementInput.getFrameMouseEvent's single per-frame fetch, also shared
    with panelInput.handlePanelInput - never call curses.getmouse() here
    directly). Toggles auto-fire, tracks mouse aim, and while firing sends
    one PLAYERSHOOT packet per projectile in the weapon's fan (confirmed via
    MITM - not one per trigger pull). A weapon fires ALL of its Subattacks
    each pull, each independently timed by its own rateOfFire (see
    SubattackDef) - a single-Subattack weapon (the common case) reduces to
    firing on one cooldown exactly as before; multi-Subattack weapons whose
    rates differ (e.g. Makakoyumi) end up interleaving instead of firing in
    lockstep. Spawns each shot into `projectiles` immediately (client-side
    prediction) rather than waiting on the server's echo; a later echo
    reuses the same (ownerId, bulletId, shotIndex) key, so it just refreshes
    the entry instead of double-spawning.
    """
    if moveDirection is not None:
        shootState.lastMoveDirection = moveDirection

    if isAutoFireToggle(keys, keybinds):
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
    subattacks = getSubattacks(projectileMap, weaponId)
    # Confirmed via MITM: whether a weapon has ANY real <Subattack> in its XML
    # (not just whether it has one, or how many distinct projectile ids it
    # has) decides the wire's 1-byte bulletId field. Legacy weapons with no
    # <Subattack> (flat NumProjectiles/ArcGap tags, e.g. Staff of Unholy
    # Sacrifice) send -1 for every shot; weapons migrated to the <Subattack>
    # shape send their real subattack.projectileId instead - even Coral Bow,
    # whose single <Subattack projectileId="0"> still sends 0, never -1.
    sendRealProjectileId = bool(subattacks)
    if not subattacks:
        # No <Subattack> - fall back to the id-0 ProjectileDefinition's own
        # numProjectiles/arcGap/rateOfFire (sourced from the flat Object-level
        # tags), not the hardcoded defaults below, which are a last resort
        # only for a weapon missing from projectileMap.json entirely.
        legacyDefinition = getProjectileDefinition(projectileMap, weaponId, 0)
        if legacyDefinition is not None:
            subattacks = [SubattackDef(
                projectileId=0, numProjectiles=max(1, legacyDefinition.numProjectiles),
                arcGapDegrees=legacyDefinition.arcGapDegrees, rateOfFire=legacyDefinition.rateOfFire,
            )]
        else:
            subattacks = [SubattackDef(
                projectileId=0, numProjectiles=_DEFAULT_NUM_PROJECTILES,
                arcGapDegrees=_DEFAULT_ARC_GAP_DEGREES, rateOfFire=_DEFAULT_RATE_OF_FIRE,
            )]

    nowMs = int(time.time() * 1000) - ticker.connectedTime
    dueSubattacks = [
        sub for sub in subattacks
        if nowMs - shootState.lastShotTimeBySubattack.get(sub.projectileId, 0) >= _attackPeriodMs(player, sub.rateOfFire)
    ]
    if not dueSubattacks:
        return

    if shootState.lastMouseWorld is not None:
        targetX, targetY = shootState.lastMouseWorld
    else:
        dx, dy = shootState.lastMoveDirection
        targetX, targetY = ticker.pos.x + dx, ticker.pos.y + dy
    baseAngle = math.atan2(targetY - ticker.pos.y, targetX - ticker.pos.x)

    shotPos = ticker.pos.clone()
    playerPos = ticker.pos.clone()

    for subattack in dueSubattacks:
        numProjectiles = max(1, subattack.numProjectiles)
        arcGapRad = math.radians(subattack.arcGapDegrees)
        bulletIdByte = subattack.projectileId if sendRealProjectileId else _DEFAULT_PROJECTILE_ID
        shotDefinition = getProjectileDefinition(projectileMap, weaponId, subattack.projectileId)

        # Fan centered on the aim direction, N-1 gaps for N projectiles -
        # confirmed against a real 4-projectile staff capture. Every shot in
        # one subattack's fan shares that subattack's own projectile id.
        for i in range(numProjectiles):
            angle = baseAngle + (i - (numProjectiles - 1) / 2) * arcGapRad

            packet = PacketHelper.createPacket("PLAYERSHOOT")
            packet.time = nowMs
            packet.shotId = shootState.nextShotId
            packet.containerType = weaponId
            packet.bulletId = bulletIdByte
            packet.shotPos = shotPos
            packet.angle = angle
            # Confirmed 0 in the one real capture on file (single-Subattack
            # weapon); RotMG's actual "Burst Fire" cooldown mechanic this
            # field name refers to is explicitly out of scope here, so this
            # stays 0 rather than guessing a "which subattack" encoding with
            # no capture to confirm it against a real account.
            packet.burstId = 0
            packet.pos = playerPos
            outgoingQueue.put(packet)

            if shotDefinition is not None:
                wavy, boomerang, parametric, magnitude, amplitude, frequency = motionParams(shotDefinition)
                projectiles.spawn(
                    bulletId=shootState.nextShotId,
                    ownerId=player.objectId,
                    startingPos=shotPos,
                    angle=angle,
                    shotIndex=i,
                    speed=shotDefinition.speed,
                    damage=shotDefinition.damage,
                    lifetimeMS=shotDefinition.lifetimeMS,
                    size=shotDefinition.size,
                    visualObjectType=shotDefinition.visualObjectType,
                    multiHit=shotDefinition.multiHit,
                    armorPiercing=shotDefinition.armorPiercing,
                    minDamage=shotDefinition.minDamage,
                    maxDamage=shotDefinition.maxDamage,
                    amplitude=amplitude,
                    frequency=frequency,
                    wavy=wavy,
                    boomerang=boomerang,
                    parametric=parametric,
                    magnitude=magnitude,
                )

            shootState.nextShotId = (shootState.nextShotId + 1) % 128

        shootState.lastShotTimeBySubattack[subattack.projectileId] = nowMs
