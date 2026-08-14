import time
from typing import List, Optional, Tuple

from Data.WorldPosData import WorldPosData
from Utils.json.aoeRadiusCacheLoader import loadAoeRadiusCache, saveAoeRadiusCache

# origType is CONFIRMED (live capture, 2026-08-14) to be the throwing enemy's
# own objectType - Tundra Yeti's "Yeti Bomb" consistently carried
# origType=31508 (0x7b14), an exact match to Tundra Yeti's real
# Resources/_generated/xml/veteran.xml objectType. Also confirmed (same
# capture): Yeti Bomb's actual pre-impact telegraph is a SHOWEFFECT with
# effectType=16 (THROW_PROJECTILE), not 4 (THROW) - its pos1 landed on the
# AOE's exact eventual position and its duration (1.4s) matched the real
# elapsed gap to landing almost exactly. THROW_PROJECTILE's `color` field is
# NOT a real color - it held 0x768, exactly Yeti Boulder's own objectType -
# so it's the flying visual projectile's objectType, reusing that wire slot
# (see spawnTelegraphIfKnown's colorHint handling). Keyed together with color
# (not origType alone): origType only identifies the ENEMY, not the specific
# ABILITY - an enemy with more than one distinct AOE attack would otherwise
# thrash one shared radius/duration between them every time either lands.
# Different abilities are likely (not guaranteed) to use different colors -
# this reduces, doesn't eliminate, that collision risk.
AoeKey = Tuple[int, int]  # (origType, color)

_TELEGRAPH_MATCH_TOLERANCE_TILES = 1.0
_LINGER_SECONDS = 0.5

# Small tolerance before a re-measured throw duration counts as "changed" -
# real network jitter alone shouldn't trip the CHANGED warning every time.
_DURATION_CHANGE_TOLERANCE_SECONDS = 0.05


class AoeTelegraph:
    """A pre-impact warning, sourced from a SHOWEFFECT(THROW) packet -
    created only by AoeStore.spawnTelegraphIfKnown, which is STRICTLY
    read-only against the confirmed tables below (SHOWEFFECT is a general-
    purpose packet used for far more than AOE, so this app's AOE handling of
    it must never write anything - only real AOE packets, via land(), do
    that). Grows from radius 0 toward the already-known targetRadius over
    durationSec, then either gets matched (and replaced) by a landed
    AoeInstance, or expires unmatched (see AoeStore.prune)."""

    def __init__(self, pos: WorldPosData, color: int, durationSec: float, key: AoeKey, targetRadius: float):
        self.pos = pos.clone()
        self.color = color
        self.startTime = time.time()
        self.durationSec = durationSec
        self.key = key
        self.targetRadius = targetRadius

    def isExpired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.startTime) >= self.durationSec

    def progress(self, now: Optional[float] = None) -> float:
        """0.0 at spawn, 1.0 at (or past) the measured/claimed impact time -
        real and trustworthy now that durationSec is either an empirically
        measured value or, at worst, a one-time fallback to the packet's own
        claim for a brand-new key (see AoeStore.spawnTelegraphIfKnown)."""
        now = time.time() if now is None else now
        if self.durationSec <= 0:
            return 1.0
        return min(1.0, (now - self.startTime) / self.durationSec)

    def currentRadius(self, now: Optional[float] = None) -> float:
        return self.targetRadius * self.progress(now)


class AoeInstance:
    """A landed AOE, sourced from an AOE packet - ground truth for radius/
    damage/effect. Rendered at full radius, fully bold, for _LINGER_SECONDS."""

    def __init__(self, pos: WorldPosData, radius: float, damage: int, effect: int, duration: float,
                 origType: int, color: int, armorPierce: bool):
        self.pos = pos.clone()
        self.radius = radius
        self.damage = damage
        self.effect = effect
        self.duration = duration  # post-hit status-effect length - NOT a visual timer
        self.origType = origType
        self.color = color
        self.armorPierce = armorPierce
        self.landTime = time.time()
        # Guards checkAoeHits (Renders/GameScreen/hitDetection.py) from
        # re-applying damage/status every frame this instance lingers.
        self.applied = False

    def isExpired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.landTime) >= _LINGER_SECONDS


class AoeStore:
    """Active AOE telegraphs/landed instances, tracked client-side - mirrors
    Models/ProjectileStore.py's shape (packet-spawned, time-based, per-frame-
    pruned). Also owns the self-teaching (origType, color) -> real
    radius/throw-duration tables, persisted to disk and grown permanently
    across restarts. Both tables are written EXCLUSIVELY by land() (real AOE
    packets, ground truth); SHOWEFFECT handling (spawnTelegraphIfKnown) only
    ever reads them - see that method's docstring.
    """

    def __init__(self):
        self.telegraphs: List[AoeTelegraph] = []
        self.instances: List[AoeInstance] = []
        self.confirmedRadii, self.confirmedDurations = loadAoeRadiusCache()

    def spawnTelegraphIfKnown(self, pos: WorldPosData, packetDuration: float,
                               enemyObjectType: Optional[int], debugger,
                               colorHint: Optional[int] = None) -> None:
        """STRICTLY READ-ONLY against confirmedRadii/confirmedDurations -
        never writes. No-ops (no telegraph at all) unless a prior AOE landing
        has already taught this enemy a real radius - there's nothing
        reliable to grow toward otherwise, so showing a placeholder-sized
        guess was removed entirely rather than kept as a fallback.

        enemyObjectType is resolved by the caller from SHOWEFFECT's
        targetObjectId (an unverified hypothesis that it's the throwing
        enemy's own object id); it only needs to agree with the AOE packet's
        own origType, which is confirmed ground truth.

        colorHint is the SHOWEFFECT's own `color` field, but it's only a
        REAL RGB color for effectType THROW (4) - CONFIRMED (live capture,
        2026-08-14) that effectType THROW_PROJECTILE (16) repurposes that
        same field to instead carry the flying visual projectile's own
        objectType (e.g. Yeti Boulder = 0x768), not a color at all. Callers
        pass colorHint=None for THROW_PROJECTILE (or anything else where the
        field isn't a real color) - in that case this falls back to matching
        any already-known key for this enemyObjectType regardless of color,
        which is ambiguous (picks arbitrarily) for an enemy with more than
        one distinct AOE color - the same known multi-ability limitation as
        the (origType, color) keying itself.
        """
        if enemyObjectType is None:
            return
        key = None
        if colorHint is not None:
            candidate = (enemyObjectType, colorHint)
            if candidate in self.confirmedRadii:
                key = candidate
        if key is None:
            key = next((k for k in self.confirmedRadii if k[0] == enemyObjectType), None)
        if key is None:
            return
        targetRadius = self.confirmedRadii[key]
        # Prefer our own empirically cross-referenced duration (measured as
        # real elapsed telegraph-to-landing time in land(), never trusted
        # blindly from the packet's own claimed field) once one exists for
        # this key; packetDuration is only a one-time animation-pacing
        # fallback for this key's very first-ever telegraph.
        durationSec = self.confirmedDurations.get(key, packetDuration)
        # The telegraph's color is always the REAL AOE color from the key
        # (key[1]), never colorHint directly - land()'s matching and the
        # actual render both need the true color, not whatever (possibly
        # unrelated) value the triggering SHOWEFFECT happened to carry.
        self.telegraphs.append(AoeTelegraph(pos, key[1], durationSec, key, targetRadius))
        debugger.debug(
            f"AOE telegraph spawned (known key={key[0]:#06x}:{key[1]:#06x}): targetRadius={targetRadius:.2f} "
            f"durationSec={durationSec:.2f} (measured={key in self.confirmedDurations}) "
            f"(colorHint={'unreliable/absent' if colorHint is None else f'{colorHint:#06x}'})"
        )

    def _popMatchingTelegraph(self, pos: WorldPosData, color: int) -> Optional[AoeTelegraph]:
        best = None
        bestDist = None
        for telegraph in self.telegraphs:
            if telegraph.color != color:
                continue
            dist = pos.dist(telegraph.pos)
            if dist > _TELEGRAPH_MATCH_TOLERANCE_TILES:
                continue
            if best is None or dist < bestDist:
                best, bestDist = telegraph, dist
        if best is not None:
            self.telegraphs.remove(best)
        return best

    def land(self, pos: WorldPosData, radius: float, damage: int, effect: int, duration: float,
              origType: int, color: int, armorPierce: bool, debugger) -> AoeInstance:
        instance = AoeInstance(pos, radius, damage, effect, duration, origType, color, armorPierce)
        self.instances.append(instance)

        telegraph = self._popMatchingTelegraph(pos, color)
        # Unconditional, every single landing - diagnostic ground truth for
        # "did an AOE even arrive" independent of whether a telegraph existed
        # to match it against.
        debugger.debug(
            f"AOE landed: pos=({pos.x:.2f},{pos.y:.2f}) radius={radius:.2f} damage={damage} effect={effect} "
            f"duration={duration:.2f} origType={origType:#06x} color={color:#06x} armorPierce={armorPierce} "
            f"matchedTelegraph={telegraph is not None}"
        )

        key = (origType, color)
        self._learnConfirmedRadius(key, radius, debugger)
        if telegraph is not None:
            measuredDuration = instance.landTime - telegraph.startTime
            self._learnConfirmedDuration(key, measuredDuration, debugger)

        return instance

    def _persist(self, debugger, reason: str) -> None:
        """The one place either confirmed table is actually written to disk -
        every caller below (learn or change) routes through this, so a real
        rewrite of the cache file is always distinctly logged, separate from
        the semantic learned/changed message describing why."""
        saveAoeRadiusCache(self.confirmedRadii, self.confirmedDurations)
        debugger.debug(
            f"AOE radius cache file rewritten ({reason}): {len(self.confirmedRadii)} radii, "
            f"{len(self.confirmedDurations)} durations"
        )

    def _learnConfirmedRadius(self, key: AoeKey, radius: float, debugger) -> None:
        prior = self.confirmedRadii.get(key)
        if prior is None:
            self.confirmedRadii[key] = radius
            self._persist(debugger, "new radius")
            debugger.info(f"AOE radius learned: key={key[0]:#06x}:{key[1]:#06x} radius={radius:.2f}")
        elif prior != radius:
            self.confirmedRadii[key] = radius
            self._persist(debugger, "changed radius")
            # A real per-ability radius shouldn't change - either a second,
            # visually-identical (same color) ability on this same enemy
            # type, or corrupted/misread data.
            debugger.warning(
                f"AOE radius CHANGED for key={key[0]:#06x}:{key[1]:#06x}: {prior:.2f} -> {radius:.2f} "
                f"(a second AOE ability sharing this origType+color, or corrupted data?)"
            )
        # else: unchanged - no log, the common/expected case every landing.

    def _learnConfirmedDuration(self, key: AoeKey, measuredDuration: float, debugger) -> None:
        prior = self.confirmedDurations.get(key)
        if prior is None:
            self.confirmedDurations[key] = measuredDuration
            self._persist(debugger, "new duration")
            debugger.info(f"AOE throw duration measured: key={key[0]:#06x}:{key[1]:#06x} measuredSec={measuredDuration:.2f}")
        elif abs(prior - measuredDuration) > _DURATION_CHANGE_TOLERANCE_SECONDS:
            self.confirmedDurations[key] = measuredDuration
            self._persist(debugger, "changed duration")
            debugger.warning(
                f"AOE throw duration CHANGED for key={key[0]:#06x}:{key[1]:#06x}: "
                f"{prior:.2f}s -> {measuredDuration:.2f}s (network jitter, or a second ability sharing this key?)"
            )
        # else: within tolerance - no log.

    def prune(self, now: Optional[float] = None, debugger=None) -> None:
        now = time.time() if now is None else now

        stillLive = []
        for telegraph in self.telegraphs:
            if telegraph.isExpired(now):
                if debugger is not None:
                    debugger.warning(
                        f"AOE telegraph expired unmatched: pos=({telegraph.pos.x:.2f},{telegraph.pos.y:.2f}) "
                        f"key={telegraph.key[0]:#06x}:{telegraph.key[1]:#06x} durationSec={telegraph.durationSec:.2f}"
                    )
            else:
                stillLive.append(telegraph)
        self.telegraphs = stillLive

        self.instances = [instance for instance in self.instances if not instance.isExpired(now)]
