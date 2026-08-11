from typing import Optional, Set

OFF = "off"
NAME = "name"
FIELDS = "fields"
LEVELS = [OFF, NAME, FIELDS]


class PacketLogSettings:
    """Shared, mutable packet-logging config - one instance lives in
    ctx["PACKET_LOG_SETTINGS"] and is handed directly to Listener/Sender at
    connect time (Networking/Connect.py), so edits made live from the pause
    menu's Debug Options screen (Renders/PauseMenu/debugOptions.py) take
    effect immediately without reconnecting."""

    def __init__(self, level: str = OFF, disabledPackets: Optional[Set[str]] = None):
        self.level = level
        self.disabledPackets: Set[str] = disabledPackets if disabledPackets is not None else set()

    def shouldLog(self, packetType: str) -> bool:
        return self.level != OFF and packetType not in self.disabledPackets

    def formatLine(self, direction: str, packet) -> str:
        if self.level == FIELDS:
            return f"{direction}: {packet}"
        return f"{direction}: {packet.type}"
