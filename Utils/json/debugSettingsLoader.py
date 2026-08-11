from typing import Set, Tuple
import json
import os
import tempfile

PERSONAL_DEBUG_SETTINGS_PATH = "Credentials/debugSettings.json"


def loadDebugSettings() -> Tuple[str, Set[str]]:
    """Loads the player's personal packet-logging prefs. No shipped default
    file (unlike keybinds) - the packet list itself is always read live from
    Constants/PacketIds.idToType, not persisted, so a new packet type added
    there later shows up already enabled with no file migration needed."""
    try:
        with open(PERSONAL_DEBUG_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # Matches the full logging just turned on directly in Listener/Sender
        # ahead of this settings screen existing - first run keeps that on
        # rather than silently reverting to off.
        return "fields", set()
    return data.get("logLevel", "off"), set(data.get("disabledPackets", []))


def saveDebugSettings(level: str, disabledPackets: Set[str]) -> None:
    if not os.path.isdir("Credentials/"):
        os.mkdir("Credentials")

    tempLoc = tempfile.NamedTemporaryFile(mode="w", dir="Credentials/", delete=False, encoding="utf-8")
    json.dump({"logLevel": level, "disabledPackets": sorted(disabledPackets)}, tempLoc, indent=4)
    tempLoc.close()
    os.replace(tempLoc.name, PERSONAL_DEBUG_SETTINGS_PATH)
