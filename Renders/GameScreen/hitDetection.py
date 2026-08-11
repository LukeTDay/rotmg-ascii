import math
import time

import Networking.PacketHelper as PacketHelper
from Constants.StatTypes import StatTypes
from Models.GameState import GameState
from Models.ProjectileStore import ProjectileStore
from Utils.json.objectNameLoader import objectRenderInfo

# UNVERIFIED best-effort estimate - no confirmed source for RotMG's real
# hitbox formula exists in this repo or in either reference bot project
# (pyrelay/rotmg_mitm_py define the ENEMYHIT/PLAYERHIT packet structs but
# never actually compute collision geometry). RotMG sprites read as roughly
# 1 tile wide at Size=100, so half-width ~0.5 tile is used as the base enemy
# radius here, scaled by the enemy's live SizeStat (falling back to its XML
# <Size> when the object has no runtime SizeStat) and by <CustomHitbox
# scale="N"> when the enemy XML overrides its hitbox independent of visual
# sprite size (~55 mostly-boss enemies). _BULLET_RADIUS_TILES is a small
# fixed allowance for the shot's own width, not derived from the
# projectile's own <Size> - keeps this one estimate instead of two.
# Recalibrate against a real MITM capture if hits look too generous/stingy.
_BASE_ENEMY_RADIUS_TILES = 0.5
_BULLET_RADIUS_TILES = 0.1

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


def _estimateDamageDealt(rawDamage: int, defense: int, armorPiercing: bool) -> int:
    if armorPiercing:
        return rawDamage
    return max(rawDamage - defense, int(rawDamage * _DEFENSE_FLOOR_FRACTION))


def _enemyRadiusTiles(obj) -> float:
    info = objectRenderInfo(obj.objectType)
    baseSize = info.baseSize if info is not None else 100
    hitboxScale = info.hitboxScale if info is not None else None

    liveSize = obj.stats.get(StatTypes.SIZESTAT)
    sizePercent = liveSize.statValue if liveSize is not None else baseSize

    radius = _BASE_ENEMY_RADIUS_TILES * (sizePercent / 100)
    if hitboxScale is not None:
        radius *= hitboxScale
    return radius


def checkProjectileHits(projectiles: ProjectileStore, state: GameState, ownerId: int,
                         nowMs: int, outgoingQueue: "object") -> None:
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

            enemyPos = obj.renderPos(now)
            dist = math.hypot(pos.x - enemyPos.x, pos.y - enemyPos.y)
            if dist > _enemyRadiusTiles(obj) + _BULLET_RADIUS_TILES:
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

            proj.hitTargetIds.add(obj.objectId)
            hitSomething = True
            if not proj.multiHit:
                break

        if hitSomething and not proj.multiHit:
            projectiles.remove(proj.ownerId, proj.bulletId, proj.shotIndex)
