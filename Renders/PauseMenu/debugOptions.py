from typing import List

import Constants.PacketIds as PacketIds
from Networking.PacketLogSettings import LEVELS, PacketLogSettings
from Utils.json.debugSettingsLoader import saveDebugSettings

# Row 0 = log level, 1 = enable-all, 2 = disable-all, 3+ = one per packet type.
_SPECIAL_ROW_COUNT = 3


def packetNames() -> List[str]:
    """Always read live off Constants/PacketIds - never hardcoded, so a
    packet type added there later shows up here already enabled, no
    migration/default-file update needed."""
    return sorted(set(PacketIds.idToType.values()))


def rowCount(names: List[str]) -> int:
    return _SPECIAL_ROW_COUNT + len(names)


def rowLabel(row: int, names: List[str], settings: PacketLogSettings) -> str:
    if row == 0:
        return f"Packet Log Level: {settings.level.upper()} (Off / Name / Fields)"
    if row == 1:
        return "Enable All Packets"
    if row == 2:
        return "Disable All Packets"
    name = names[row - _SPECIAL_ROW_COUNT]
    mark = " " if name in settings.disabledPackets else "X"
    return f"[{mark}] {name}"


def activate(row: int, names: List[str], settings: PacketLogSettings, debugger) -> None:
    if row == 0:
        settings.level = LEVELS[(LEVELS.index(settings.level) + 1) % len(LEVELS)]
    elif row == 1:
        settings.disabledPackets.clear()
    elif row == 2:
        settings.disabledPackets = set(names)
    else:
        name = names[row - _SPECIAL_ROW_COUNT]
        if name in settings.disabledPackets:
            settings.disabledPackets.discard(name)
        else:
            settings.disabledPackets.add(name)

    saveDebugSettings(settings.level, settings.disabledPackets)
    debugger.info(f"Debug settings changed: level={settings.level} disabledCount={len(settings.disabledPackets)}")
