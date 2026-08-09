import xml.etree.ElementTree as et
from typing import Dict, Optional

from Models.GroundTypeData import GroundTypeData

GROUND_XML_PATH = "Resources/ground.xml"


def _parseTypeAttr(raw: str) -> Optional[int]:
    try:
        return int(raw, 16)
    except (TypeError, ValueError):
        return None


def _parseFloat(elem: Optional[et.Element], default: float) -> float:
    if elem is None or not elem.text:
        return default
    try:
        return float(elem.text)
    except ValueError:
        return default


def _parseInt(elem: Optional[et.Element], default: int) -> int:
    if elem is None or not elem.text:
        return default
    try:
        return int(elem.text)
    except ValueError:
        return default


def _parseColor(elem: Optional[et.Element]) -> Optional[int]:
    if elem is None or not elem.text:
        return None
    try:
        return int(elem.text, 16)
    except ValueError:
        return None


def parseGroundTypes(xmlText: str) -> Dict[int, GroundTypeData]:
    """Pure parse: XML text -> {groundTypeId: GroundTypeData}. No disk IO here -
    kept separate from _readGroundXml() so a future automated-fetch step can
    hand this function a downloaded string directly instead of a file path."""
    groundTypes: Dict[int, GroundTypeData] = {}
    root = et.fromstring(xmlText)
    for ground in root.findall("Ground"):
        typeAttr = ground.get("type")
        idAttr = ground.get("id")
        if typeAttr is None or idAttr is None:
            continue
        groundType = _parseTypeAttr(typeAttr)
        if groundType is None:
            continue
        displayIdElem = ground.find("DisplayId")
        name = displayIdElem.text if displayIdElem is not None and displayIdElem.text else idAttr
        groundTypes[groundType] = GroundTypeData(
            groundType=groundType,
            name=name,
            speed=_parseFloat(ground.find("Speed"), 1.0),
            minDamage=_parseInt(ground.find("MinDamage"), 0),
            maxDamage=_parseInt(ground.find("MaxDamage"), 0),
            noWalk=ground.find("NoWalk") is not None,
            sink=ground.find("Sink") is not None,
            color=_parseColor(ground.find("Color")),
        )
    return groundTypes


def _readGroundXml(path: str = GROUND_XML_PATH) -> Optional[str]:
    """Isolated disk-read step so a future automated fetch of a newer
    ground.xml could replace just this function later without touching the
    parser or callers."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except IOError:
        return None


_groundTypesCache: Optional[Dict[int, GroundTypeData]] = None


def _loadGroundTypes() -> Dict[int, GroundTypeData]:
    global _groundTypesCache
    if _groundTypesCache is None:
        xmlText = _readGroundXml()
        _groundTypesCache = parseGroundTypes(xmlText) if xmlText is not None else {}
    return _groundTypesCache


def groundIdToData(groundType: int) -> Optional[GroundTypeData]:
    """Mirrors Utils.XML.parseObjectNames.objectIdToName's shape: never
    raises, returns None for unknown/missing ids so callers can fall back
    gracefully."""
    return _loadGroundTypes().get(groundType)
