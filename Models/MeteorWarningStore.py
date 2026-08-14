import time
from typing import List, Optional

from Data.WorldPosData import WorldPosData


class MeteorWarning:
    """A ground marker showing where a meteor will land - a fixed 1-tile
    warning glyph, unlike AoeStore's telegraphs: no learned/growing radius,
    just visible for durationSec (the SHOWEFFECT packet's own claimed value -
    there's no follow-up "landed" packet confirmed for METEOR to cross-
    reference against, unlike AOE's THROW/AOE pair) then it clears."""

    def __init__(self, pos: WorldPosData, durationSec: float):
        self.pos = pos.clone()
        self.startTime = time.time()
        self.durationSec = durationSec

    def isExpired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.startTime) >= self.durationSec


class MeteorWarningStore:
    """Active meteor-warning markers, tracked client-side - mirrors
    Models/AoeStore.py's shape (packet-spawned, time-based, per-frame-
    pruned), but deliberately much simpler: no learning, no persistence, no
    hit-detection - just a visible '!' marker for the warning's duration."""

    def __init__(self):
        self.warnings: List[MeteorWarning] = []

    def spawn(self, pos: WorldPosData, durationSec: float) -> None:
        self.warnings.append(MeteorWarning(pos, durationSec))

    def prune(self, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self.warnings = [w for w in self.warnings if not w.isExpired(now)]
