import json
import xml.etree.ElementTree as et
from pathlib import Path
from typing import Dict, List, Optional

from Models.GroundTypeData import GroundTypeData

# Resources/ground.xml (this module's original source) is stale - it was
# superseded by Scripts/AssetPipeline's extraction into Resources/_generated/
# (see .gitignore/CLAUDE.md) and no longer exists on disk, which silently
# left every groundIdToData() lookup returning None. Read from the same
# manifest-listed generated files the asset pipeline itself uses instead.
GENERATED_XML_DIR = Path("Resources/_generated/xml")
MANIFEST_PATH = Path("Resources/_generated/json/manifest.json")


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
    kept separate from the file-loading loop in _loadGroundTypes() so each
    generated XML file's text can be handed to it independently."""
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


def _loadTileFileNames(manifest_path: Path = MANIFEST_PATH) -> List[str]:
    """Reads the same manifest.json Scripts/AssetPipeline/parseGameXml.py
    uses, returning its "tiles" file list in order - the global ground.xml
    first, then ~55 per-dungeon override files (e.g. dungeon-specific lava/
    chasm variants). Never raises: an unreadable/missing manifest just means
    no ground types load, same fail-open posture as a single missing file."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (IOError, OSError, json.JSONDecodeError):
        return []
    return [Path(entry["path"]).stem for entry in manifest.get("tiles", [])]


_groundTypesCache: Optional[Dict[int, GroundTypeData]] = None


def _loadGroundTypes() -> Dict[int, GroundTypeData]:
    """Merges every ground-type XML file the manifest lists under "tiles" -
    later files win on id collision, mirroring parseGameXml.py's parseAll()
    exactly, so this runtime loader and the asset pipeline agree on which
    ground type a given id resolves to."""
    global _groundTypesCache
    if _groundTypesCache is None:
        merged: Dict[int, GroundTypeData] = {}
        for name in _loadTileFileNames():
            path = GENERATED_XML_DIR / f"{name}.xml"
            if not path.is_file():
                continue
            try:
                xmlText = path.read_text(encoding="utf-8")
            except (IOError, OSError):
                continue
            merged.update(parseGroundTypes(xmlText))
        _groundTypesCache = merged
    return _groundTypesCache


def groundIdToData(groundType: int) -> Optional[GroundTypeData]:
    """Mirrors Utils.XML.parseObjectNames.objectIdToName's shape: never
    raises, returns None for unknown/missing ids so callers can fall back
    gracefully."""
    return _loadGroundTypes().get(groundType)
