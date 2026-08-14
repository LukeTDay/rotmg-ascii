import math
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import Networking.PacketHelper as PacketHelper
from Constants.StatTypes import StatTypes
from Constants.StatusEffects import INVINCIBLE, INVULNERABLE
from Models.ConditionEffect import hasEffect
from Models.GameState import GameState
from Models.ProjectileStore import ProjectileStore
from Utils.json.objectNameLoader import objectRenderInfo

# Confirmed: enemy hitbox is a fixed 0.5-tile radius regardless of visual
# <Size>/SizeStat - only an explicit <CustomHitbox scale="N"> (~55 mostly-
# boss enemies) overrides it.
_BASE_ENEMY_RADIUS_TILES = 0.5

# EXPERIMENTAL (was +0.1, a generous allowance for the shot's own width):
# Evil Chicken God got zero DAMAGE back across 708 sends all within the old
# 0.6 cutoff (debug.txt, 2026-08-11) - trying a tighter cutoff than the base
# radius itself to see if it correlates with real confirmations instead.
# Still scales with <CustomHitbox scale> like the old allowance did (applied
# after _enemyRadiusTiles' multiply, not before) - only the default-enemy
# case changes size (0.5 -> 0.45).
_SEND_THRESHOLD_MARGIN_TILES = -0.05

# Off while full packet logging (Networking/Listener.py, Networking/Sender.py)
# covers the same ground more generally - flip back on to get this module's
# own higher-level ENEMYHIT/DAMAGE-match narration instead of raw packets.
_VERBOSE_HIT_LOGGING = False


@dataclass
class _PendingHit:
    bulletId: int
    targetId: int
    sentAtMs: float
    distance: float
    radius: float
    enemyObjectType: int
    enemyName: str
    hpAtSend: int


class HitTracker:
    """Diagnostic instrumentation for calibrating the UNVERIFIED
    _enemyRadiusTiles estimate above: tracks every ENEMYHIT this client sends
    and confirms it by watching the target's own HPSTAT drop below its
    send-time value in a later UPDATE/NEWTICK - not by matching the DAMAGE
    packet. A real capture (rotmg_mitm_py/mitm.log, 2026-08-11) showed only
    ~1 DAMAGE per 13 ENEMYHIT sends across the whole log, and the one entry
    with full field data was a damageAmount=0 curse-effect tick, not a hit
    ack - DAMAGE isn't a general per-hit confirmation channel, so matching
    against it was never going to work regardless of timing/key-collision
    fixes. HP dropping confirms the send-time distance was inside the real
    hitbox; a timeout with no drop proves it wasn't.
    """

    # NEWTICK arrives on the server's own steady tick cadence - much faster
    # and far more reliable than waiting on the rare DAMAGE packet. 5s is
    # generous headroom, not a measured round trip like the old 30s was.
    _CONFIRM_TIMEOUT_MS = 5000.0

    def __init__(self):
        self._pending: Dict[Tuple[int, int], _PendingHit] = {}

    def recordSent(self, bulletId: int, targetId: int, distance: float, radius: float,
                    enemyObjectType: int, enemyName: str, hpAtSend: int) -> None:
        self._pending[(bulletId, targetId)] = _PendingHit(
            bulletId, targetId, time.time() * 1000, distance, radius, enemyObjectType, enemyName, hpAtSend
        )

    def checkHpDrop(self, targetId: int, newHp: int, debugger) -> None:
        """Called for every fresh HPSTAT reading (UPDATE/NEWTICK) on any
        tracked object - confirms every still-pending send against this
        target whose recorded hpAtSend baseline is higher than newHp. Can't
        attribute a drop to one specific send when several are pending on the
        same target at once (e.g. Energy Staff's 2-shot volley all sharing
        one hpAtSend baseline) - confirms all of them in that case, an
        accepted over-count for a calibration tool, not something anything
        downstream relies on being exact.
        """
        confirmedKeys = [key for key, p in self._pending.items() if key[1] == targetId and newHp < p.hpAtSend]
        for key in confirmedKeys:
            p = self._pending.pop(key)
            if _VERBOSE_HIT_LOGGING:
                debugger.debug(
                    f"HIT CONFIRMED (HP {p.hpAtSend}->{newHp}): {p.enemyName} (type={p.enemyObjectType}) "
                    f"bulletId={p.bulletId} distanceAtSend={p.distance:.3f} estimatedRadius={p.radius:.3f}"
                )

    def pruneTimeouts(self, debugger) -> None:
        nowMs = time.time() * 1000
        expired = [key for key, p in self._pending.items() if nowMs - p.sentAtMs >= self._CONFIRM_TIMEOUT_MS]
        for key in expired:
            p = self._pending.pop(key)
            if _VERBOSE_HIT_LOGGING:
                debugger.warning(
                    f"HIT NOT CONFIRMED (no HP drop within {self._CONFIRM_TIMEOUT_MS:.0f}ms): "
                    f"{p.enemyName} (type={p.enemyObjectType}) bulletId={p.bulletId} "
                    f"distanceAtSend={p.distance:.3f} estimatedRadius={p.radius:.3f}"
                )


# How long a boss stays pinned as the displayed target (Renders/GameScreen/
# enemyHealthBar.py) after the last hit on it, before a hit on something else
# is allowed to switch the display - refreshed on every re-hit of the boss.
_BOSS_LOCK_MS = 3000.0

# Default minimum gap between any two target switches, for every creature
# (boss or not) - without this, hitting several enemies in the same frame/
# volley (e.g. a piercing shot, or a fast weapon tagging two mobs a tick
# apart) makes the bar flicker between them.
_SWITCH_COOLDOWN_MS = 250.0


class EnemyTargetTracker:
    """Tracks which enemy the local player is "currently fighting" for the
    top-of-screen HP bar - fed from the same per-frame hit loop as
    HitTracker above (checkProjectileHits calls recordHit right where it
    calls hitTracker.recordSent). A non-boss hit switches the display once
    _SWITCH_COOLDOWN_MS has passed since the last switch; a boss hit instead
    pins the display to it for _BOSS_LOCK_MS, refreshed on every further hit
    on that same boss, so hitting adjacent trash mobs mid-fight doesn't
    bounce the bar away from the boss.
    """

    def __init__(self):
        self.targetId: Optional[int] = None
        self.isBossTarget: bool = False
        self.bossLockUntil: float = 0.0
        self.lastSwitchMs: float = -math.inf

    def recordHit(self, objectId: int, isBoss: bool, nowMs: float) -> None:
        if self.targetId == objectId:
            if isBoss:
                self.bossLockUntil = nowMs + _BOSS_LOCK_MS
            return
        if self.targetId is not None:
            if self.isBossTarget and nowMs < self.bossLockUntil:
                return  # still locked onto the current boss - ignore other hits
            if nowMs - self.lastSwitchMs < _SWITCH_COOLDOWN_MS:
                return  # switched too recently - ignore for now
        self.targetId = objectId
        self.isBossTarget = isBoss
        self.bossLockUntil = nowMs + _BOSS_LOCK_MS if isBoss else 0.0
        self.lastSwitchMs = nowMs

    def clear(self) -> None:
        self.targetId = None
        self.isBossTarget = False
        self.bossLockUntil = 0.0
        self.lastSwitchMs = -math.inf


def _enemyRadiusTiles(obj) -> float:
    info = objectRenderInfo(obj.objectType)
    hitboxScale = info.hitboxScale if info is not None else None

    radius = _BASE_ENEMY_RADIUS_TILES
    if hitboxScale is not None:
        radius *= hitboxScale
    return radius


def checkProjectileHits(projectiles: ProjectileStore, state: GameState, ownerId: int,
                         nowMs: int, outgoingQueue: "object", hitTracker: HitTracker,
                         targetTracker: EnemyTargetTracker, debugger) -> None:
    """Client-side hit detection for the local player's own in-flight shots.
    RotMG expects the shooter's own client to report ENEMYHIT (confirmed via
    MITM capture) - the server has no fine-grained collision of its own to
    fall back on, so shots that never get reported never register. Only
    checks projectiles this connection owns (`ownerId` match); shots fired by
    other players or enemies are that shooter's own client's responsibility,
    not ours.

    A non-multiHit projectile is removed from `projectiles` immediately on
    its first hit (matches real behavior - it stops instead of continuing to
    fly through). A multiHit (piercing) projectile keeps flying and can hit
    additional enemies later in its lifetime, but never the same enemy twice
    - `Projectile.hitTargetIds` guards that per-shot, not just per-frame.

    Every send is also handed to `hitTracker` (confirmed via HP drop, watched
    by gameScreen.py) - see HitTracker's docstring for why: the
    hit-radius estimate below is unverified, and bosses in particular
    (confirmed via Dreadstump the Pirate King's XML - Size=100, no
    <CustomHitbox> override) can visually dwarf the radius that formula
    gives them, so tracking confirmed-vs-unconfirmed sends is how to tell
    whether a given enemy's estimate is actually wrong.
    """
    now = time.time()
    for proj in list(projectiles.projectiles.values()):
        if proj.ownerId != ownerId or proj.isExpired(now):
            continue

        pos = proj.posAt(now)
        hitSomething = False
        for obj in state.objects.values():
            if obj.objectId in proj.hitTargetIds:
                continue
            info = objectRenderInfo(obj.objectType)
            if info is None or not info.isEnemy:
                continue

            # Confirmed live: Evil Chicken God sends zero DAMAGE back for its
            # entire invulnerable window despite in-range ENEMYHIT sends -
            # skip sending against a target flagged INVINCIBLE/INVULNERABLE
            # (Constants/StatusEffects.py) instead of wasting a claim the
            # server will never honor. Re-checked every frame (not cached),
            # so this naturally starts sending again once the condition clears.
            condition = obj.stats.get(StatTypes.CONDITIONSTAT)
            if condition is not None and hasEffect(condition.statValue, INVINCIBLE, INVULNERABLE):
                continue

            enemyPos = obj.renderPos(now)
            dist = math.hypot(pos.x - enemyPos.x, pos.y - enemyPos.y)
            radius = _enemyRadiusTiles(obj)
            if dist > radius + _SEND_THRESHOLD_MARGIN_TILES:
                continue

            liveHp = obj.stats.get(StatTypes.HPSTAT)

            packet = PacketHelper.createPacket("ENEMYHIT")
            packet.time = nowMs
            packet.bulletId = proj.bulletId
            packet.id1 = ownerId
            packet.targetId = obj.objectId
            packet.kill = False  # never claim a kill - let the server decide
            packet.id2 = ownerId
            outgoingQueue.put(packet)
            if liveHp is not None:
                hitTracker.recordSent(proj.bulletId, obj.objectId, dist, radius, obj.objectType, info.name, liveHp.statValue)
            targetTracker.recordHit(obj.objectId, info.isBoss, nowMs)
            if _VERBOSE_HIT_LOGGING:
                debugger.debug(
                    f"ENEMYHIT sent: {info.name} (type={obj.objectType}) bulletId={proj.bulletId} "
                    f"distance={dist:.3f} estimatedRadius={radius:.3f}"
                )

            proj.hitTargetIds.add(obj.objectId)
            hitSomething = True
            if not proj.multiHit:
                break

        if hitSomething and not proj.multiHit:
            projectiles.remove(proj.ownerId, proj.bulletId, proj.shotIndex)


# RotMG's real player collision radius - unlike enemies, every player uses
# the same fixed 0.5-tile hitbox regardless of class/size.
_PLAYER_RADIUS_TILES = 0.5


def checkPlayerHits(projectiles: ProjectileStore, ownerId: int, playerPos,
                     outgoingQueue: "object", debugger) -> None:
    """Client-side hit detection for enemy projectiles against the local
    player - the mirror of checkProjectileHits above, but incoming instead
    of outgoing. Same protocol convention as ENEMYHIT: the client on the
    receiving end reports the hit (PLAYERHIT), and the server applies the
    real damage/defense math and echoes the reduced HPSTAT back on the next
    NEWTICK - which the HUD HP bar (Renders/GameScreen/inventoryPanel.
    drawBars) already renders straight from player.hp, so no extra plumbing
    is needed for it to show up.

    Only checks projectiles flagged `fromEnemy` at spawn time (see
    Models/ProjectileStore.py) - never the local player's own shots, and
    never another player's (this app doesn't track other players' shots as
    a threat since PvP isn't a thing in these realms).
    """
    if playerPos is None:
        return
    now = time.time()
    for proj in list(projectiles.projectiles.values()):
        if not proj.fromEnemy or proj.ownerId == ownerId or proj.hitLocalPlayer or proj.isExpired(now):
            continue

        pos = proj.posAt(now)
        dist = math.hypot(pos.x - playerPos.x, pos.y - playerPos.y)
        if dist > _PLAYER_RADIUS_TILES:
            continue

        packet = PacketHelper.createPacket("PLAYERHIT")
        packet.bulletId = proj.bulletId
        packet.objectId = proj.ownerId
        outgoingQueue.put(packet)
        proj.hitLocalPlayer = True
        if _VERBOSE_HIT_LOGGING:
            debugger.debug(f"PLAYERHIT sent: ownerId={proj.ownerId} bulletId={proj.bulletId} distance={dist:.3f}")

        if not proj.multiHit:
            projectiles.remove(proj.ownerId, proj.bulletId, proj.shotIndex)


# Same fixed 0.5-tile hitbox as _PLAYER_RADIUS_TILES above - real RotMG uses
# one constant player collision radius regardless of class/size.
_AOE_PLAYER_RADIUS_TILES = 0.5


def checkAoeHits(aoeStore, player, playerPos, debugger) -> None:
    """Client-side AOE collision against the local player - unlike
    checkPlayerHits (which reports a hit and waits for the server's real
    HPSTAT/CONDITIONSTAT), this applies damage/status LOCALLY and
    immediately: the server already applies AOE damage on its own timer with
    no client action required (confirmed via alloy-server's
    AOEDamager.AOEActivate), so there's no packet to send here - only a local
    prediction, which the next authoritative HPSTAT/CONDITIONSTAT will
    silently correct if it's wrong (e.g. non-armor-piercing AOEs, where this
    client has no defense-mitigation formula to reduce `instance.damage` by).

    Gated by `AoeInstance.applied` so each landed instance is only ever
    applied once, regardless of how many frames it lingers for.
    """
    if playerPos is None:
        return
    for instance in aoeStore.instances:
        if instance.applied:
            continue
        instance.applied = True

        dist = math.hypot(instance.pos.x - playerPos.x, instance.pos.y - playerPos.y)
        if dist > _AOE_PLAYER_RADIUS_TILES:
            continue

        if player.maxHp:
            player.hp = max(0, min(player.maxHp, player.hp - instance.damage))
        else:
            player.hp = max(0, player.hp - instance.damage)

        # Only effects 1-31 fit this app's single-word `player.condition`
        # bitmask (CONDITIONSTAT) - effects 32-59 need a second word
        # (condition2/NEWCONSTAT) this app doesn't parse at all today, a
        # pre-existing gap unrelated to AOE. Silently no-op rather than
        # mis-encoding a bit into the wrong word.
        if 1 <= instance.effect <= 31:
            base = player.condition if isinstance(player.condition, int) else 0
            player.condition = base | (1 << (instance.effect - 1))
            player.conditionExpiry[instance.effect] = time.time() + instance.duration

        debugger.debug(f"AOE hit applied: damage={instance.damage} effect={instance.effect} dist={dist:.3f}")


def pruneExpiredConditions(player) -> None:
    """Clears any condition bit this client applied locally (see
    checkAoeHits) once its recorded duration has elapsed. The only local
    condition-expiry mechanism in this app - CONDITIONSTAT is otherwise
    always a wholesale server-sent replacement, never locally timed."""
    now = time.time()
    expired = [effect for effect, expiry in player.conditionExpiry.items() if now >= expiry]
    for effect in expired:
        base = player.condition if isinstance(player.condition, int) else 0
        player.condition = base & ~(1 << (effect - 1))
        del player.conditionExpiry[effect]
