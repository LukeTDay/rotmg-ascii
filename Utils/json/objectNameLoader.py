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
    isPortal: bool = False
    isInteractiveNpc: bool = False
    isBeacon: bool = False
    isBeaconMarker: bool = False
    # Equipment-item fields for the item-info-peek/inventory UI - absent
    # (falls back to these defaults) on every non-equipment object, since
    # renderMap.json only carries them for `<Object>` elements that had the
    # underlying XML fields. See Scripts/AssetPipeline/deriveRenderInfo.py
    # for how weaponLabel/bagColorTier are derived.
    weaponLabel: str = ""
    bagColorTier: str = "WHITE"
    # Item-info-peek fields (tier/mpCost/mpEndCost/description) - see
    # Scripts/AssetPipeline/deriveRenderInfo.py for how these are derived.
    # Absent (falls back to these defaults) on renderMap.json entries
    # generated before this field set existed, or on non-equipment objects
    # that never had the underlying XML fields.
    tier: Optional[int] = None
    mpCost: Optional[int] = None
    mpEndCost: Optional[int] = None
    description: str = ""
    # Hit-detection fields (client-side ENEMYHIT geometry) - see
    # Scripts/AssetPipeline/parseGameXml.ParsedEntity's field comment for
    # what these mean and Renders/GameScreen/hitDetection.py for their use.
    baseSize: int = 100
    hitboxScale: Optional[float] = None


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
                isPortal=entry.get("isPortal", False),
                isInteractiveNpc=entry.get("isInteractiveNpc", False),
                isBeacon=entry.get("isBeacon", False),
                isBeaconMarker=entry.get("isBeaconMarker", False),
                weaponLabel=entry.get("weaponLabel", ""),
                bagColorTier=entry.get("bagColorTier", "WHITE"),
                tier=entry.get("tier"),
                mpCost=entry.get("mpCost"),
                mpEndCost=entry.get("mpEndCost"),
                description=entry.get("description", ""),
                baseSize=entry.get("baseSize", 100),
                hitboxScale=entry.get("hitboxScale"),
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
