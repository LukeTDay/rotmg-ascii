import xml.etree.ElementTree as et
from typing import Dict, Optional

OBJECT_XML_PATH = "Resources/object.xml"


def _parseTypeAttr(raw: str) -> Optional[int]:
    try:
        return int(raw, 16)
    except (TypeError, ValueError):
        return None


def parseObjectNames(xmlText: str) -> Dict[int, str]:
    """Pure parse: XML text -> {objectTypeId: displayName}. No disk IO here -
    kept separate from _readObjectXml() so a future automated-fetch step can
    hand this function a downloaded string directly instead of a file path."""
    names: Dict[int, str] = {}
    root = et.fromstring(xmlText)
    for obj in root.findall("Object"):
        typeAttr = obj.get("type")
        idAttr = obj.get("id")
        if typeAttr is None or idAttr is None:
            continue
        objectId = _parseTypeAttr(typeAttr)
        if objectId is None:
            continue
        displayIdElem = obj.find("DisplayId")
        name = displayIdElem.text if displayIdElem is not None and displayIdElem.text else idAttr
        names[objectId] = name
    return names


def _readObjectXml(path: str = OBJECT_XML_PATH) -> Optional[str]:
    """Isolated disk-read step so a future automated fetch of a newer
    object.xml could replace just this function later without touching the
    parser or callers."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except IOError:
        return None


_objectNamesCache: Optional[Dict[int, str]] = None


def _loadObjectNames() -> Dict[int, str]:
    global _objectNamesCache
    if _objectNamesCache is None:
        xmlText = _readObjectXml()
        _objectNamesCache = parseObjectNames(xmlText) if xmlText is not None else {}
    return _objectNamesCache


def objectIdToName(objectId: int) -> Optional[str]:
    """Mirrors Constants.ClassIds.idToClass's shape: never raises, returns
    None for unknown/missing ids so callers can fall back gracefully."""
    return _loadObjectNames().get(objectId)
