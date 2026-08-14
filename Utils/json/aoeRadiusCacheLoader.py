from typing import Dict, Tuple
import json
import os
import tempfile

AOE_RADIUS_CACHE_DIR = "Resources/"
AOE_RADIUS_CACHE_PATH = AOE_RADIUS_CACHE_DIR + "aoeRadiusCache.json"

AoeKey = Tuple[int, int]  # (origType, color) - see Models/AoeStore.py


def _parseKeyedFloats(raw) -> Dict[AoeKey, float]:
    result: Dict[AoeKey, float] = {}
    if not isinstance(raw, dict):
        return result
    for key, value in raw.items():
        try:
            origTypeStr, colorStr = key.split(":", 1)
            result[(int(origTypeStr), int(colorStr))] = float(value)
        except (ValueError, AttributeError):
            continue
    return result


def loadAoeRadiusCache() -> Tuple[Dict[AoeKey, float], Dict[AoeKey, float]]:
    """Confirmed (origType, color) -> real AOE blast radius, and -> measured
    real throw-to-impact duration, both self-taught exclusively from live AOE
    packets (see Models/AoeStore.py's land()) and persisted across restarts.
    Returns ({}, {}) if nothing's been learned yet or the file is malformed."""
    try:
        with open(AOE_RADIUS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}
    return _parseKeyedFloats(data.get("radii", {})), _parseKeyedFloats(data.get("durations", {}))


def saveAoeRadiusCache(radii: Dict[AoeKey, float], durations: Dict[AoeKey, float]) -> None:
    """Atomically writes both confirmed tables together, mirroring
    keybindLoader.saveKeybinds's tempfile+os.replace pattern. JSON object
    keys must be strings, so (origType, color) tuples are encoded as
    "origType:color" on write and parsed back on load."""
    os.makedirs(AOE_RADIUS_CACHE_DIR, exist_ok=True)

    data = {
        "radii": {f"{origType}:{color}": radius for (origType, color), radius in radii.items()},
        "durations": {f"{origType}:{color}": duration for (origType, color), duration in durations.items()},
    }
    tempLoc = tempfile.NamedTemporaryFile(mode="w", dir=AOE_RADIUS_CACHE_DIR, delete=False, encoding="utf-8")
    json.dump(data, tempLoc, indent=4)
    tempLoc.close()
    os.replace(tempLoc.name, AOE_RADIUS_CACHE_PATH)
