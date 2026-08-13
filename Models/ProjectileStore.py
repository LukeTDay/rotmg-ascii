import math
import random
import time
from typing import Dict, Optional, Set, Tuple

from Data.WorldPosData import WorldPosData


class Projectile:
    def __init__(self, bulletId: int, ownerId: int, shotIndex: int, startingPos: WorldPosData, angle: float,
                 speed: float, damage: int, lifetimeMS: int, size: Optional[int] = None,
                 visualObjectType: Optional[int] = None, multiHit: bool = False, armorPiercing: bool = False,
                 minDamage: Optional[int] = None, maxDamage: Optional[int] = None,
                 amplitude: float = 0.0, frequency: float = 0.0, fromEnemy: bool = False,
                 wavy: bool = False, boomerang: bool = False, parametric: bool = False,
                 magnitude: float = 0.0):
        self.bulletId = bulletId
        self.ownerId = ownerId
        self.shotIndex = shotIndex
        self.startingPos = startingPos.clone()
        self.angle = angle
        self.speed = speed
        # Rolled once at spawn, not re-rolled per target - matches "this
        # shot's power was set when fired," not per-hit. `damage` is only
        # used as a fixed value when the weapon has no min/max range (a
        # flat <Damage> tag - some non-random attacks); most weapons roll
        # between minDamage/maxDamage instead, same as the real server does.
        self.damage = random.randint(minDamage, maxDamage) if minDamage is not None and maxDamage is not None else damage
        self.lifetimeMS = lifetimeMS
        self.size = size
        # Own renderMap.json objectType (separate <Object> from the firer);
        # None falls back to a fixed color.
        self.visualObjectType = visualObjectType
        self.spawnTime = time.time()
        # Piercing shots (multiHit=True) keep flying and can hit more than
        # one enemy over their lifetime; non-multiHit shots stop at the
        # first. hitTargetIds guards against re-reporting the same enemy
        # every frame while still overlapping it - see
        # Renders/GameScreen/hitDetection.py.
        self.multiHit = multiHit
        # Bypasses the target's defense entirely for kill-guess purposes -
        # see Renders/GameScreen/hitDetection.py's damage-after-defense estimate.
        self.armorPiercing = armorPiercing
        # Motion-type fields, all confirmed against real extracted game XML
        # (Resources/_generated/xml - <Wavy/>, <Boomerang/>, <Parametric/>,
        # <Magnitude>, <Amplitude>, <Frequency> all genuinely appear, not
        # guesses) and cross-checked formula-for-formula against 2-3
        # independent reference implementations (Club559/ROTMGServer,
        # alloy-server, realm-engine-client's ProjectileSimulator.ts - see
        # CLAUDE.local.md's "Reference projects" section). wavy/boomerang/
        # parametric are mutually exclusive branches in posAt(); amplitude/
        # frequency only apply in the plain/boomerang branch (real
        # <Amplitude>/<Frequency> can coexist with <Boomerang/>, confirmed
        # in all 3 sources). All default to inert values so a projectile
        # with none of these extras reduces to plain straight-line motion.
        self.wavy = wavy
        self.boomerang = boomerang
        self.parametric = parametric
        self.magnitude = magnitude
        self.amplitude = amplitude
        self.frequency = frequency
        self.hitTargetIds: Set[int] = set()
        # Set at spawn (ENEMYSHOOT vs SERVERPLAYERSHOOT) - lets hitDetection.
        # checkPlayerHits tell an enemy's bullet from a player's own without
        # re-deriving it later from state.objects, which may no longer have
        # the shooter (e.g. it died) by the time the projectile is checked.
        self.fromEnemy = fromEnemy
        # A player-hitting bullet can only hit the local player once; unlike
        # hitTargetIds (per-enemy-id, for multiHit shots hitting several
        # enemies) there's only ever one local player to track.
        self.hitLocalPlayer = False

    def isExpired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.spawnTime) * 1000 >= self.lifetimeMS

    def posAt(self, now: Optional[float] = None) -> WorldPosData:
        now = time.time() if now is None else now
        elapsedSec = now - self.spawnTime
        elapsedMs = elapsedSec * 1000.0
        lifetimeFrac = (elapsedMs / self.lifetimeMS) if self.lifetimeMS else 0.0
        # Adjacent shots in a fan (even/odd shotIndex) get opposite phase so
        # a multi-shot volley weaves rather than moving in lockstep -
        # confirmed identically in all 3 reference sources for both Wavy
        # and the Amplitude/Frequency offset below.
        period = 0.0 if self.shotIndex % 2 == 0 else math.pi

        if self.wavy:
            # Angle itself oscillates (not a lateral offset) - amplitude
            # PI/64 rad and period 6*PI rad/s confirmed by both alloy-server
            # (WavyPath.cs) and realm-engine-client's ProjectileSimulator.ts;
            # Club559's Math.PI*64 is very likely a transcription bug (see
            # CLAUDE.local.md).
            theta = self.angle + (math.pi / 64) * math.sin(period + 6 * math.pi * elapsedSec)
            dist = self.speed * elapsedSec
            return WorldPosData(
                self.startingPos.x + math.cos(theta) * dist,
                self.startingPos.y + math.sin(theta) * dist,
            )

        if self.parametric:
            # Ignores speed/dist entirely - a Lissajous curve scaled by
            # Magnitude, traced once over the shot's full lifetime. a/b sign
            # flips by shotIndex parity so a multi-shot volley fans out into
            # distinct curve variants instead of overlapping.
            theta = lifetimeFrac * 2 * math.pi
            a = math.sin(theta) * (1.0 if self.shotIndex % 2 != 0 else -1.0)
            b = math.sin(2 * theta) * (1.0 if self.shotIndex % 4 < 2 else -1.0)
            cosA, sinA = math.cos(self.angle), math.sin(self.angle)
            return WorldPosData(
                self.startingPos.x + (a * cosA - b * sinA) * self.magnitude,
                self.startingPos.y + (a * sinA + b * cosA) * self.magnitude,
            )

        dist = self.speed * elapsedSec
        if self.boomerang:
            # Reflects at the lifetime's temporal midpoint - travels out,
            # then back along the same line.
            halfDist = self.speed * (self.lifetimeMS / 1000.0) / 2
            if dist > halfDist:
                dist = 2 * halfDist - dist
        x = self.startingPos.x + math.cos(self.angle) * dist
        y = self.startingPos.y + math.sin(self.angle) * dist
        if self.amplitude:
            # Perpendicular sine offset, phased by elapsed-lifetime fraction
            # (a fixed number of Frequency cycles over the whole flight) -
            # NOT by distance traveled like this used to compute it, which
            # made the wavelength scale with speed instead of staying fixed
            # per shot.
            offset = self.amplitude * math.sin(period + lifetimeFrac * self.frequency * 2 * math.pi)
            x -= math.sin(self.angle) * offset
            y += math.cos(self.angle) * offset
        return WorldPosData(x, y)


class ProjectileStore:
    """Active in-flight bullets, tracked client-side - RotMG never resends a
    projectile's position after the shoot packet, so flight is simulated
    from startingPos/angle/speed until lifetimeMS expires.

    Keyed by (ownerId, bulletId, shotIndex): bulletId alone can collide
    across different multi-shot bursts from the same owner if the fanned
    index were folded into it, so shotIndex is kept separate instead -
    hit-reporting needs the real bulletId sent back unmodified.

    speed/lifetimeMS/size aren't in the shoot packets - spawn() takes them
    as explicit args since XML-definition lookup isn't wired up yet.
    """

    def __init__(self):
        self.projectiles: Dict[Tuple[int, int, int], Projectile] = {}

    def spawn(self, bulletId: int, ownerId: int, startingPos: WorldPosData, angle: float,
              speed: float, damage: int, lifetimeMS: int, size: Optional[int] = None, shotIndex: int = 0,
              visualObjectType: Optional[int] = None, multiHit: bool = False, armorPiercing: bool = False,
              minDamage: Optional[int] = None, maxDamage: Optional[int] = None,
              amplitude: float = 0.0, frequency: float = 0.0, fromEnemy: bool = False,
              wavy: bool = False, boomerang: bool = False, parametric: bool = False,
              magnitude: float = 0.0) -> None:
        key = (ownerId, bulletId, shotIndex)
        self.projectiles[key] = Projectile(
            bulletId, ownerId, shotIndex, startingPos, angle, speed, damage, lifetimeMS, size, visualObjectType,
            multiHit, armorPiercing, minDamage, maxDamage, amplitude, frequency, fromEnemy,
            wavy, boomerang, parametric, magnitude,
        )

    def remove(self, ownerId: int, bulletId: int, shotIndex: int = 0) -> None:
        self.projectiles.pop((ownerId, bulletId, shotIndex), None)

    def prune(self, now: Optional[float] = None) -> None:
        # Enemy-hit detection/reporting lives in Renders/GameScreen/
        # hitDetection.py (called before this each frame) - this only prunes
        # on expiry (or after hitDetection.py removes a non-multiHit shot
        # that already connected).
        now = time.time() if now is None else now
        expired = [key for key, proj in self.projectiles.items() if proj.isExpired(now)]
        for key in expired:
            del self.projectiles[key]
