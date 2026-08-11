import curses
import math
import textwrap
import time
from typing import Dict, Optional, Set

from Constants import ColorPairs
from Models.GameState import GameObject, GameState
from Models.TileManager import _TIER_PRIORITY, classifyObject
from Renders.GameScreen.uiPanel import PanelLayout, centeredCol
from Utils.json.objectNameLoader import objectRenderInfo
from Utils.json.projectileMapLoader import OwnerEntry, getProjectileDefinition

# Known equipment-category tokens that can appear in ObjectRenderInfo.
# weaponLabel's comma-split <Labels> text (e.g. "EQUIPMENT,WEAPON,SWORD,
# TIERED,LOOTABLE,T0,TRADEABLE,BASETYPE") - searched for a TYPE line instead
# of just dumping the raw label string, falling back to the raw string if
# none of these match (e.g. an EQUIPMENT-flagged item this list doesn't
# cover yet).
_EQUIPMENT_CATEGORIES = (
    "SWORD", "DAGGER", "BOW", "WAND", "STAFF", "TOME", "SEAL", "TRAP",
    "KATANA", "QUIVER", "SHIELD", "HELM", "ARMOR", "RING",
)

_PLACEHOLDER_TEXT = "Click an item or tile"


def resolveClickedObject(state: GameState, listenerObjectId: int, worldX: float, worldY: float,
                          friendsList: Set[str], guildMembers: Set[str],
                          lockedAccounts: Set[str]) -> Optional[GameObject]:
    """Screen-click -> game-object resolution: nothing in this repo currently
    maps a click's world position to a specific GameObject (only to a raw
    world x/y, via mapRenderer.screenToWorld, already used by shoot-aim).
    Mirrors Models/TileManager.py's tier-priority logic exactly (imports and
    reuses classifyObject/_TIER_PRIORITY rather than reinventing the
    precedence rules) - among every object whose position floors to the same
    tile as the click, the one with the highest-priority tier wins, same as
    which glyph would actually be drawn there. Same renderPos-for-others/pos-
    for-self pattern TileManager.buildVisibleTiles uses.
    """
    tileX, tileY = math.floor(worldX), math.floor(worldY)
    now = time.time()
    best: Optional[GameObject] = None
    bestPriority: Optional[int] = None
    for obj in state.objects.values():
        pos = obj.pos if obj.objectId == listenerObjectId else obj.renderPos(now)
        if math.floor(pos.x) != tileX or math.floor(pos.y) != tileY:
            continue
        info = objectRenderInfo(obj.objectType)
        tier = classifyObject(obj, listenerObjectId, info, friendsList, guildMembers, lockedAccounts)
        if tier is None:
            continue
        priority = _TIER_PRIORITY.index(tier)
        if bestPriority is None or priority < bestPriority:
            bestPriority = priority
            best = obj
    return best


def _resolveTypeLabel(weaponLabel: str) -> str:
    tokens = [t.strip() for t in weaponLabel.split(",")]
    for token in tokens:
        if token in _EQUIPMENT_CATEGORIES:
            return token
    return weaponLabel  # no recognized category token - show the raw label instead


def drawItemInfoPeek(pad: curses.window, layout: PanelLayout, peekedObjectType: Optional[int],
                      projectileMap: Dict[int, OwnerEntry]) -> None:
    """Draws into the panel's top section: NAME always, plus TYPE/TIER/MP
    COST/DESCRIPTION/RATE OF FIRE+DAMAGE when peekedObjectType resolves to an
    equipment item (weaponLabel non-empty). Truncates rather than scrolling
    if the section's rows run out - not perfect, just crash-safe.
    `peekedObjectType` is re-resolved (objectRenderInfo/projectileMap) fresh
    every frame by the caller, not cached - see Context.PEEKED_OBJECT_TYPE's
    doc comment.
    """
    section = layout.topSection
    maxRow = section.startRow + section.height
    attr = curses.color_pair(ColorPairs.DEFAULT)
    row = section.startRow

    def writeLine(text: str) -> bool:
        nonlocal row
        if row >= maxRow:
            return False
        clipped = text[:max(1, layout.panelWidth)]
        try:
            pad.addstr(row, centeredCol(layout, len(clipped)), clipped, attr)
        except curses.error:
            pass
        row += 1
        return True

    if peekedObjectType is None:
        writeLine(_PLACEHOLDER_TEXT)
        return

    info = objectRenderInfo(peekedObjectType)
    if info is None:
        writeLine("Unknown object")
        return

    writeLine(info.name or "Unknown")

    if not info.weaponLabel:
        return  # not equipment - name is all there is to show

    if not writeLine(f"TYPE: {_resolveTypeLabel(info.weaponLabel)}"):
        return
    if info.tier is not None:
        if not writeLine(f"TIER: {info.tier}"):
            return
    if info.mpCost is not None:
        costText = f"MP COST: {info.mpCost}"
        if info.mpEndCost is not None and info.mpEndCost != info.mpCost:
            costText += f"-{info.mpEndCost}"
        if not writeLine(costText):
            return

    definition = getProjectileDefinition(projectileMap, peekedObjectType, 0)
    if definition is not None:
        if not writeLine(f"RATE OF FIRE: {definition.rateOfFire}"):
            return
        if definition.minDamage is not None and definition.maxDamage is not None:
            if not writeLine(f"DAMAGE: {definition.minDamage}-{definition.maxDamage}"):
                return
        elif definition.damage:
            if not writeLine(f"DAMAGE: {definition.damage}"):
                return

    if info.description:
        for line in textwrap.wrap(info.description, max(1, layout.panelWidth)):
            if not writeLine(line):
                return
