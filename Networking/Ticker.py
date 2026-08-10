import threading
import time

from Data.WorldPosData import WorldPosData
from Data.MoveRecord import MoveRecord
from Models.ConditionEffect import hasEffect
from Constants.StatusEffects import SLOWED, SPEEDY, NINJASPEEDY

TICK_INTERVAL = 1 / 60

# RotMG's real movement-speed formula (tiles/ms; confirmed against two reference
# projects). SLOWED overrides to flat MIN_SPEED; SPEEDY/NINJASPEEDY apply 1.5x
# on top of the stat-derived speed, skipped if SLOWED already short-circuited it.
MIN_SPEED = 0.004
MAX_SPEED = 0.0096
HASTE_MULTIPLIER = 1.5


def computeSpeed(spd: int, spdBoost: int, condition: int) -> float:
    if hasEffect(condition, SLOWED):
        return MIN_SPEED
    speed = MIN_SPEED + (spd + spdBoost) / 75 * (MAX_SPEED - MIN_SPEED)
    if hasEffect(condition, SPEEDY, NINJASPEEDY):
        speed *= HASTE_MULTIPLIER
    return speed


class RepeatTimer(threading.Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


class Ticker:
    """Dead-reckons movement locally on a steady 60Hz clock between server ticks;
    never touches the socket or either queue itself."""

    def __init__(self, connectedTime: int, debugger) -> None:
        self.connectedTime = connectedTime
        self.debugger = debugger
        self.pos: WorldPosData | None = None
        self.target: WorldPosData | None = None
        self.speed = MIN_SPEED  # updated via setSpeed() once real stats arrive
        self.records: list[MoveRecord] = []
        self.lastFrameTime = self._getTime()
        self._lock = threading.Lock()
        self._timer: RepeatTimer | None = None
        self.active = True

    def start(self):
        self.debugger.info("Ticker started")
        self._timer = RepeatTimer(TICK_INTERVAL, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def stop(self):
        self.debugger.info("Ticker stopped")
        self.active = False
        if self._timer is not None:
            self._timer.cancel()

    def setPos(self, pos: WorldPosData):
        with self._lock:
            self.pos = pos.clone()

    def setTarget(self, pos: WorldPosData):
        with self._lock:
            self.target = pos.clone()

    def setSpeed(self, speed: float):
        with self._lock:
            self.speed = speed

    def drainRecords(self) -> list[MoveRecord]:
        with self._lock:
            records = self.records
            self.records = []
        return records

    def _getTime(self) -> int:
        return int(time.time() * 1000) - self.connectedTime

    def _tick(self):
        if not self.active:
            return
        now = self._getTime()
        diff = min(100, now - self.lastFrameTime)
        self.lastFrameTime = now

        with self._lock:
            if self.pos is None:
                return
            if self.target is not None and self.pos.dist(self.target) > 1e-6:
                step = self.speed * diff
                if self.pos.dist(self.target) <= step:
                    self.pos = self.target.clone()
                else:
                    dx = self.target.x - self.pos.x
                    dy = self.target.y - self.pos.y
                    dist = self.pos.dist(self.target)
                    self.pos = WorldPosData(
                        self.pos.x + dx / dist * step,
                        self.pos.y + dy / dist * step,
                    )
            self.records.append(MoveRecord(now, self.pos.x, self.pos.y))
