import math
import time
from dataclasses import dataclass
from typing import Dict, Tuple

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

# UNVERIFIED best-effort estimate - no confirmed source for RotMG's real
# damage-vs-defense formula exists in this repo or in either reference bot
# project (rotmg_mitm_py/pyrelay/realmlib only document the DEFENSESTAT
# field, never a formula). Commonly cited community constant: armor-piercing
# hits ignore defense entirely; non-piercing hits are reduced by defense but
# never below this floor fraction of the raw roll. Used only for `kill` -
# an optional hint the server can freely ignore/override, not something the
# server trusts for the actual damage applied (ENEMYHIT carries no damage
# field at all - the server rolls/applies that itself). Recalibrate if kill
# claims look consistently early/late once tested live.
_DEFENSE_FLOOR_FRACTION = 0.30

# Off while full packet logging (Networking/Listener.py, Networking/Sender.py)
# covers the same ground more generally - flip back on to get this module's
# own higher-level ENEMYHIT/DAMAGE-match narration instead of raw packets.
_VERBOSE_HIT_LOGGING = False


def _estimateDamageDealt(rawDamage: int, defense: int, armorPiercing: bool) -> int:
    if armorPiercing:
        return rawDamage
    return max(rawDamage - defense, int(rawDamage * _DEFENSE_FLOOR_FRACTION))


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


def _enemyRadiusTiles(obj) -> float:
    info = objectRenderInfo(obj.objectType)
    hitboxScale = info.hitboxScale if info is not None else None

    radius = _BASE_ENEMY_RADIUS_TILES
    if hitboxScale is not None:
        radius *= hitboxScale
    return radius


def checkProjectileHits(projectiles: ProjectileStore, state: GameState, ownerId: int,
                         nowMs: int, outgoingQueue: "object", hitTracker: HitTracker, debugger) -> None:
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
            kill = False
            if liveHp is not None:
                liveDefense = obj.stats.get(StatTypes.DEFENSESTAT)
                defense = liveDefense.statValue if liveDefense is not None else 0
                dealt = _estimateDamageDealt(proj.damage, defense, proj.armorPiercing)
                kill = liveHp.statValue - dealt <= 0
            # else: enemy's current HP isn't tracked (no UPDATE/NEWTICK for
            # it yet) - can't guess, stays False. Server decides regardless.

            packet = PacketHelper.createPacket("ENEMYHIT")
            packet.time = nowMs
            packet.bulletId = proj.bulletId
            packet.id1 = ownerId
            packet.targetId = obj.objectId
            packet.kill = kill
            packet.id2 = ownerId
            outgoingQueue.put(packet)
            if liveHp is not None:
                hitTracker.recordSent(proj.bulletId, obj.objectId, dist, radius, obj.objectType, info.name, liveHp.statValue)
            if _VERBOSE_HIT_LOGGING:
                debugger.debug(
                    f"ENEMYHIT sent: {info.name} (type={obj.objectType}) bulletId={proj.bulletId} "
                    f"distance={dist:.3f} estimatedRadius={radius:.3f} kill={kill}"
                )

            proj.hitTargetIds.add(obj.objectId)
            hitSomething = True
            if not proj.multiHit:
                break

        if hitSomething and not proj.multiHit:
            projectiles.remove(proj.ownerId, proj.bulletId, proj.shotIndex)
