import json
from typing import Dict, Optional

RENDER_MAP_PATH = "Resources/renderMap.json"

_objectNamesCache: Optional[Dict[int, str]] = None


def _loadObjectNames() -> Dict[int, str]:
    global _objectNamesCache
    if _objectNamesCache is None:
        try:
            with open(RENDER_MAP_PATH, "r", encoding="utf-8") as f:
                renderMap = json.load(f)
        except (IOError, json.JSONDecodeError):
            renderMap = {}
        _objectNamesCache = {
            int(idStr): entry["name"]
            for idStr, entry in renderMap.get("objects", {}).items()
            if "name" in entry
        }
    return _objectNamesCache


def objectIdToName(objectId: int) -> Optional[str]:
    """Mirrors Constants.ClassIds.idToClass's shape: never raises, returns
    None for unknown/missing ids so callers can fall back gracefully (e.g.
    charSelect.py's _equipSlotText falls back to str(objectId))."""
    return _loadObjectNames().get(objectId)
