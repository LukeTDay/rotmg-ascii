from typing import Optional


class GroundTypeData:
    def __init__(self,
                 groundType: int,
                 name: str,
                 speed: float,
                 minDamage: int,
                 maxDamage: int,
                 noWalk: bool,
                 sink: bool,
                 color: Optional[int]) -> None:
        self.groundType = groundType
        self.name = name
        self.speed = speed
        self.minDamage = minDamage
        self.maxDamage = maxDamage
        self.noWalk = noWalk
        self.sink = sink
        self.color = color
