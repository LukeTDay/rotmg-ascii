import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

RENDER_MAP_PATH = "Resources/renderMap.json"


@dataclass(frozen=True)
class ObjectRenderInfo:
    name: str
    chars: List[str] = field(default_factory=lambda: ["*"])
    color: str = "WHITE"
    blocksMovement: bool = False
    isEnemy: bool = False
    isLootBag: bool = False


@dataclass(frozen=True)
class GroundRenderInfo:
    name: str
    chars: List[str] = field(default_factory=lambda: ["."])
    color: str = "WHITE"


_renderMapCache: Optional[dict] = None
_objectInfoCache: Optional[Dict[int, ObjectRenderInfo]] = None
_groundInfoCache: Optional[Dict[int, GroundRenderInfo]] = None


def _loadRenderMap() -> dict:
    global _renderMapCache
    if _renderMapCache is None:
        try:
            with open(RENDER_MAP_PATH, "r", encoding="utf-8") as f:
                _renderMapCache = json.load(f)
        except (IOError, json.JSONDecodeError):
            _renderMapCache = {}
    return _renderMapCache


def _loadObjectInfo() -> Dict[int, ObjectRenderInfo]:
    global _objectInfoCache
    if _objectInfoCache is None:
        _objectInfoCache = {
            int(idStr): ObjectRenderInfo(
                name=entry["name"],
                chars=entry.get("chars", ["*"]),
                color=entry.get("color", "WHITE"),
                blocksMovement=entry.get("blocksMovement", False),
                isEnemy=entry.get("isEnemy", False),
                isLootBag=entry.get("isLootBag", False),
            )
            for idStr, entry in _loadRenderMap().get("objects", {}).items()
            if "name" in entry
        }
    return _objectInfoCache


def _loadGroundInfo() -> Dict[int, GroundRenderInfo]:
    global _groundInfoCache
    if _groundInfoCache is None:
        _groundInfoCache = {
            int(idStr): GroundRenderInfo(
                name=entry["name"],
                chars=entry.get("chars", ["."]),
                color=entry.get("color", "WHITE"),
            )
            for idStr, entry in _loadRenderMap().get("ground", {}).items()
            if "name" in entry
        }
    return _groundInfoCache


def objectRenderInfo(objectId: int) -> Optional[ObjectRenderInfo]:
    """Mirrors Constants.ClassIds.idToClass's shape: never raises, returns
    None for unknown/missing ids so callers can fall back gracefully."""
    return _loadObjectInfo().get(objectId)


def groundRenderInfo(groundType: int) -> Optional[GroundRenderInfo]:
    """Mirrors Constants.ClassIds.idToClass's shape: never raises, returns
    None for unknown/missing ids so callers can fall back gracefully."""
    return _loadGroundInfo().get(groundType)


def objectIdToName(objectId: int) -> Optional[str]:
    """Mirrors Constants.ClassIds.idToClass's shape: never raises, returns
    None for unknown/missing ids so callers can fall back gracefully (e.g.
    charSelect.py's _equipSlotText falls back to str(objectId))."""
    info = objectRenderInfo(objectId)
    return info.name if info is not None else None
