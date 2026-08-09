import threading
import time

from Data.WorldPosData import WorldPosData
from Data.MoveRecord import MoveRecord

TICK_INTERVAL = 1 / 10
# Placeholder until a live PlayerData/condition-effect object exists to read the
# real speed stat from during an active connection.
DEFAULT_SPEED = 0.006


class RepeatTimer(threading.Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


class Ticker:
    """Local movement dead-reckoning between server ticks. Runs on its own steady
    10Hz clock, independent of the network and render loop - never touches the
    socket or either queue itself."""

    def __init__(self, connectedTime: int) -> None:
        self.connectedTime = connectedTime
        self.pos: WorldPosData | None = None
        self.target: WorldPosData | None = None
        self.records: list[MoveRecord] = []
        self.lastFrameTime = self._getTime()
        self._lock = threading.Lock()
        self._timer: RepeatTimer | None = None
        self.active = True

    def start(self):
        self._timer = RepeatTimer(TICK_INTERVAL, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def stop(self):
        self.active = False
        if self._timer is not None:
            self._timer.cancel()

    def setPos(self, pos: WorldPosData):
        with self._lock:
            self.pos = pos.clone()

    def setTarget(self, pos: WorldPosData):
        with self._lock:
            self.target = pos.clone()

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
                step = DEFAULT_SPEED * diff
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
