import curses
import math
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from Constants import ClassIds, ColorPairs
from Constants.StatTypes import StatTypes
from Models.Context import Context
from Models.GameState import GameObject, GameState
from Models.TileManager import Tier, classifyObject
from Networking.Ticker import Ticker
from Renders.GameScreen.inventoryPanel import CELL_GAP, GRID_COLS, _cellContent, _cellWidthAndStride
from Renders.GameScreen.uiPanel import PanelLayout, centeredCol, drawGridDividers, evenlySpacedRows
from Utils.json.objectNameLoader import objectRenderInfo

# How close (world tiles) a loot bag has to be to ticker.pos to show up in
# the bottom panel at all - hand-tunable, not derived from anything. Portals
# use exact same-tile detection instead (see _isOnSameTile) - real RotMG
# portal use requires actually standing on the portal, not just being near
# it, per user request.
NEARBY_RANGE_TILES = 2.0

_BAG_GRID_COLS = 4
_BAG_GRID_ROWS = 2
_BAG_SLOT_COUNT = _BAG_GRID_COLS * _BAG_GRID_ROWS

_ENTER_BUTTON_TEXT = "[ENTER]"
_CYCLE_BUTTON_WIDTH = 8  # generous fixed rect - actual text ("[>] i/n") varies with digit count

# Row offsets from the section's first usable content row (_contentStartRow).
_NAME_ROW_OFFSET = 0
_ENTER_ROW_OFFSET = 1
_PORTAL_CYCLE_ROW_OFFSET = 2

_BAG_LABEL_ROW_OFFSET = 0
_BAG_GRID_ROW_OFFSET = 1

_DEFAULT_MAP_ROW_OFFSET = 0
_DEFAULT_PLAYERS_ROW_OFFSET = 1
# 1 blank row below "Players: N" before the nearby-players grid starts -
# same "1 blank row of spacing below the last one" convention as
# inventoryPanel._GRID_TOP_OFFSET.
_NEARBY_PLAYERS_GRID_TOP_OFFSET = _DEFAULT_PLAYERS_ROW_OFFSET + 2

# 2 wide bars instead of inventory's 4 narrow cells, per user request - each
# bar spans this many adjacent inventory columns merged together (so a bar's
# x-position/width is still derived from inventoryPanel's own column math,
# just fewer/wider columns), landing exactly on inventory's own internal
# column-2 divider rather than an independent 2-column split of the panel.
_NEARBY_PLAYERS_GRID_COLS = 2
_NEARBY_PLAYERS_COLS_PER_BAR = GRID_COLS // _NEARBY_PLAYERS_GRID_COLS


@dataclass(frozen=True)
class ActiveWidget:
    """What the bottom panel is currently showing - computed once per frame
    by resolveActiveWidget and shared between the draw call and click-
    dispatch (Renders/GameScreen/panelInput.py) so they never disagree about
    what's actually on screen, same pattern inventoryPanel's draw/hit-test
    pair already follows."""
    kind: str  # "portal" | "bag" | "default"
    candidates: List[GameObject] = field(default_factory=list)  # sorted by objectId
    selected: Optional[GameObject] = None  # candidates[cycleIndex], or None for "default"
    cycleIndex: int = 0


def _isOnSameTile(a, b) -> bool:
    """Whole-tile equality (math.floor per axis), not a distance threshold -
    a Euclidean distance check (even a tight one) doesn't reliably mean "same
    tile", since two points near opposite corners of one tile can be up to
    sqrt(2) apart while two points in adjacent tiles can be much closer than
    that."""
    return math.floor(a.x) == math.floor(b.x) and math.floor(a.y) == math.floor(b.y)


def _nearbyCandidates(state: GameState, ticker: Ticker, listenerObjectId: int, friendsList: Set[str],
                       guildMembers: Set[str], lockedAccounts: Set[str], tier: Tier) -> List[GameObject]:
    if ticker.pos is None:
        return []
    now = time.time()
    result = []
    for obj in state.objects.values():
        info = objectRenderInfo(obj.objectType)
        objTier = classifyObject(obj, listenerObjectId, info, friendsList, guildMembers, lockedAccounts)
        if objTier != tier:
            continue
        pos = obj.pos if obj.objectId == listenerObjectId else obj.renderPos(now)
        if tier == Tier.PORTAL:
            # Real RotMG portal use requires actually standing on the portal,
            # not just being near it - per user request.
            inRange = _isOnSameTile(ticker.pos, pos)
        else:
            # WorldPosData.dist's exact calling convention - same as
            # Networking/Ticker.py's own movement-arrival check.
            inRange = ticker.pos.dist(pos) <= NEARBY_RANGE_TILES
        if inRange:
            result.append(obj)
    result.sort(key=lambda o: o.objectId)
    return result


def resolveActiveWidget(ctx: Context, state: GameState, ticker: Ticker, listenerObjectId: int,
                         friendsList: Set[str], guildMembers: Set[str], lockedAccounts: Set[str]) -> ActiveWidget:
    """Priority: portal candidates beat bag candidates beat the no-nearby-
    entity default. Safe to call more than once in the same frame (draw,
    then click-dispatch) - resets/re-derives from the same unchanged state
    both times, so the second call is a no-op past the first.
    """
    portals = _nearbyCandidates(state, ticker, listenerObjectId, friendsList, guildMembers, lockedAccounts,
                                 Tier.PORTAL)
    if portals:
        kind, candidates = "portal", portals
    else:
        bags = _nearbyCandidates(state, ticker, listenerObjectId, friendsList, guildMembers, lockedAccounts,
                                  Tier.LOOT_BAG)
        kind, candidates = ("bag", bags) if bags else ("default", [])

    candidateIds = frozenset(obj.objectId for obj in candidates)
    prevIds = ctx.get("BOTTOM_PANEL_CANDIDATE_IDS")
    if prevIds != candidateIds:
        # The winning tier's candidate set changed since last frame (walked
        # up to a different bag/portal, or away from one entirely) - the old
        # cycle index no longer means anything, so reset it rather than
        # pointing at a stale/out-of-range candidate.
        ctx["BOTTOM_PANEL_CYCLE_INDEX"] = 0
    ctx["BOTTOM_PANEL_CANDIDATE_IDS"] = candidateIds

    cycleIndex = ctx.setdefault("BOTTOM_PANEL_CYCLE_INDEX", 0)
    selected = None
    if candidates:
        cycleIndex %= len(candidates)
        ctx["BOTTOM_PANEL_CYCLE_INDEX"] = cycleIndex
        selected = candidates[cycleIndex]
    return ActiveWidget(kind=kind, candidates=candidates, selected=selected, cycleIndex=cycleIndex)


def _bagInventory(obj: GameObject) -> List[int]:
    """A loot bag's GameObject.stats carries INVENTORY0STAT..INVENTORY7STAT
    exactly like a player's own inventory stats do - read into an 8-slot
    list (-1 for any missing stat), mirroring PlayerData.parseStats' own
    INVENTORY0..11STAT handling."""
    inv = [-1] * _BAG_SLOT_COUNT
    for i in range(_BAG_SLOT_COUNT):
        stat = obj.stats.get(StatTypes.INVENTORY0STAT + i)
        if stat is not None:
            inv[i] = stat.statValue
    return inv


def _nearbyPlayerCount(state: GameState) -> int:
    """Counts every player-class GameObject this client currently knows
    about (via UPDATE) - not filtered down to the friend/guild/locked-
    account subset classifyObject actually renders, since this is meant as a
    population count, not a render list. NOTE this only reflects players
    within this client's currently-loaded/nearby region (whatever the server
    has sent UPDATEs for), not necessarily the map's true full population -
    an honest approximation, not a guess presented as fact (same spirit as
    PlayerData.backpackSlots' documented assumption)."""
    return sum(1 for obj in state.objects.values() if ClassIds.idToClass(obj.objectType) is not None)


# Nearby-player-grid coloring, per user request: base color is purely
# seasonal-or-not (reads the live SEASONAL wire stat directly - a nearby
# player isn't in this client's own char/list, unlike CharSelect's
# isSeasonal flag, which only covers the logged-in account's own
# characters); locked/friend/guild don't get their own colors, they just
# bold whichever base color already applies. Locked/friend/guild reuse the
# exact account-id/name lookups Models/TileManager.py's
# otherPlayerRelationship already established for the map renderer.
_DEFAULT_COLOR_NAME = "YELLOW"
_SEASONAL_COLOR_NAME = "GREEN"


def _nearbyPlayerAttr(obj: GameObject, name: str, guildMembers: Set[str], friendsList: Set[str],
                       lockedAccounts: Set[str]) -> int:
    seasonalStat = obj.stats.get(StatTypes.SEASONAL)
    isSeasonal = seasonalStat is not None and bool(seasonalStat.statValue)
    colorName = _SEASONAL_COLOR_NAME if isSeasonal else _DEFAULT_COLOR_NAME
    attr = curses.color_pair(ColorPairs.MAP_COLOR_TO_PAIR[colorName])

    accountIdStat = obj.stats.get(StatTypes.ACCOUNTIDSTAT)
    accountId = accountIdStat.strStatValue if accountIdStat is not None else None
    isLocked = accountId is not None and accountId in lockedAccounts
    if isLocked or name in friendsList or name in guildMembers:
        attr |= curses.A_BOLD
    return attr


def _nearbyPlayerNames(state: GameState, ticker: Ticker, listenerObjectId: int, guildMembers: Set[str],
                        friendsList: Set[str], lockedAccounts: Set[str]) -> List[Tuple[str, int]]:
    """(name, curses attr) for every OTHER player-class GameObject this
    client currently knows about (the local player is excluded - no point
    listing yourself), closest-to-farthest from ticker.pos so the most
    relevant names are the ones kept if there isn't room for all of them.
    Recomputed fresh every frame - state.objects.values() is already fully
    scanned unthrottled for _nearbyPlayerCount right below this in
    drawBottomPanel, so sorting the (usually much smaller) player subset on
    top costs little in comparison.
    """
    now = time.time()
    players = [obj for obj in state.objects.values()
               if obj.objectId != listenerObjectId and ClassIds.idToClass(obj.objectType) is not None]
    if ticker.pos is not None:
        players.sort(key=lambda o: ticker.pos.dist(o.renderPos(now)))

    entries = []
    for obj in players:
        nameStat = obj.stats.get(StatTypes.NAMESTAT)
        if nameStat is not None and nameStat.strStatValue:
            # NAMESTAT carries "Name,Title" when a title is equipped - only
            # the name (index 0) belongs in this list, and is what's checked
            # against guildMembers/friendsList below too (titled or not).
            name = nameStat.strStatValue.split(",")[0]
            entries.append((name, _nearbyPlayerAttr(obj, name, guildMembers, friendsList, lockedAccounts)))
    return entries


def _contentStartRow(layout: PanelLayout) -> int:
    """First usable row inside the bottom section, just below its top
    section-divider row (drawn by uiPanel.drawPanelFrame) - same pattern as
    inventoryPanel._contentStartRow for the middle section."""
    return layout.bottomSection.startRow + 1


def _writeLine(pad: curses.window, row: int, col: int, text: str, width: int,
               attr: int = curses.A_NORMAL) -> None:
    try:
        pad.addstr(row, col, text[:max(1, width)], attr)
    except curses.error:
        pass


def _cycleButtonRect(layout: PanelLayout, row: int) -> Tuple[int, int, int]:
    width = _CYCLE_BUTTON_WIDTH
    colStart = layout.panelStartCol + max(0, layout.panelWidth - width)
    colEnd = colStart + width
    return row, colStart, colEnd


def _bagGridRowStartAndStride(layout: PanelLayout) -> Tuple[int, int]:
    """Spreads the bag grid's 2 rows evenly between just-below-the-label and
    the bottom section's own bottom edge - same "push toward the end of the
    section, even spacing between rows" treatment as inventoryPanel's own
    grid (see uiPanel.evenlySpacedRows), per user request to extend the bag
    UI the same way."""
    topBound = _contentStartRow(layout) + _BAG_GRID_ROW_OFFSET
    bottomBound = layout.bottomSection.startRow + layout.bottomSection.height - 1
    return evenlySpacedRows(topBound, bottomBound, _BAG_GRID_ROWS)


def drawBottomPanel(pad: curses.window, layout: PanelLayout, ctx: Context, state: GameState, ticker: Ticker,
                     listenerObjectId: int, friendsList: Set[str], guildMembers: Set[str],
                     lockedAccounts: Set[str]) -> None:
    widget = resolveActiveWidget(ctx, state, ticker, listenerObjectId, friendsList, guildMembers, lockedAccounts)
    startRow = _contentStartRow(layout)
    defaultAttr = curses.color_pair(ColorPairs.DEFAULT)

    if widget.kind == "portal" and widget.selected is not None:
        info = objectRenderInfo(widget.selected.objectType)
        name = info.name if info is not None else "Portal"
        _writeLine(pad, startRow + _NAME_ROW_OFFSET, centeredCol(layout, len(name)), name, layout.panelWidth,
                   defaultAttr)
        _writeLine(pad, startRow + _ENTER_ROW_OFFSET, centeredCol(layout, len(_ENTER_BUTTON_TEXT)),
                   _ENTER_BUTTON_TEXT, layout.panelWidth, defaultAttr)
        if len(widget.candidates) > 1:
            cycleRow, cycleCol, _ = _cycleButtonRect(layout, startRow + _PORTAL_CYCLE_ROW_OFFSET)
            cycleText = f"[>] {widget.cycleIndex + 1}/{len(widget.candidates)}"
            _writeLine(pad, cycleRow, cycleCol, cycleText, layout.panelWidth, defaultAttr)

    elif widget.kind == "bag" and widget.selected is not None:
        labelRow = startRow + _BAG_LABEL_ROW_OFFSET
        _writeLine(pad, labelRow, centeredCol(layout, len("BAG")), "BAG", layout.panelWidth, defaultAttr)
        if len(widget.candidates) > 1:
            cycleRow, cycleCol, _ = _cycleButtonRect(layout, labelRow)
            cycleText = f"[>] {widget.cycleIndex + 1}/{len(widget.candidates)}"
            _writeLine(pad, cycleRow, cycleCol, cycleText, layout.panelWidth, defaultAttr)

        inv = _bagInventory(widget.selected)
        gridStartRow, rowStride = _bagGridRowStartAndStride(layout)
        cellWidth, colStride = _cellWidthAndStride(layout.panelWidth)
        gridStartCol = layout.panelStartCol
        drawGridDividers(pad, gridStartCol, gridStartRow, rowStride, colStride, CELL_GAP, _BAG_GRID_ROWS,
                          _BAG_GRID_COLS)
        for i in range(_BAG_SLOT_COUNT):
            row, gridCol = divmod(i, _BAG_GRID_COLS)
            screenRow = gridStartRow + row * rowStride
            screenCol = gridStartCol + gridCol * colStride
            text, pairNum = _cellContent(inv[i], cellWidth)
            try:
                pad.addstr(screenRow, screenCol, text, curses.color_pair(pairNum))
            except curses.error:
                pass

    else:
        mapName = ctx.get("CURR_MAP_NAME", "")
        playerCountText = f"Players: {_nearbyPlayerCount(state)}"
        _writeLine(pad, startRow + _DEFAULT_MAP_ROW_OFFSET, centeredCol(layout, len(mapName)), mapName,
                   layout.panelWidth, defaultAttr)
        _writeLine(pad, startRow + _DEFAULT_PLAYERS_ROW_OFFSET, centeredCol(layout, len(playerCountText)),
                   playerCountText, layout.panelWidth, defaultAttr)

        # Nearby-player-names grid: 2 wide bars (not inventory's 4 narrow
        # cells) whose x-positions are still derived from inventoryPanel's
        # own gridStartCol/colStride - per user request, so the bar boundary
        # lands exactly on one of inventory's own column dividers and the
        # two grids still line up visually despite being in different
        # sections. The grid's SIZE is fixed to whatever fits in the
        # available space (maxRows x _NEARBY_PLAYERS_GRID_COLS) regardless
        # of how many names there actually are - same "always-drawn
        # structure, filled in with whatever content exists" relationship inventoryPanel's own
        # grid has with player.inv (empty slots still draw, just blank).
        topBound = startRow + _NEARBY_PLAYERS_GRID_TOP_OFFSET
        bottomBound = layout.bottomSection.startRow + layout.bottomSection.height - 1
        maxRows = max(0, bottomBound - topBound + 1)  # tightest (stride=1) fit - see evenlySpacedRows
        if maxRows > 0:
            entries = _nearbyPlayerNames(state, ticker, listenerObjectId, guildMembers, friendsList, lockedAccounts)
            rowStart, rowStride = evenlySpacedRows(topBound, bottomBound, maxRows)
            _, colStride = _cellWidthAndStride(layout.panelWidth)
            gridStartCol = layout.panelStartCol
            barStride = colStride * _NEARBY_PLAYERS_COLS_PER_BAR
            barWidth = barStride - CELL_GAP
            drawGridDividers(pad, gridStartCol, rowStart, rowStride, barStride, CELL_GAP, maxRows,
                              _NEARBY_PLAYERS_GRID_COLS)
            for i in range(maxRows * _NEARBY_PLAYERS_GRID_COLS):
                row, col = divmod(i, _NEARBY_PLAYERS_GRID_COLS)
                screenRow = rowStart + row * rowStride
                screenCol = gridStartCol + col * barStride
                if i < len(entries):
                    name, attr = entries[i]
                    # Truncated (names can run up to 15 characters) before
                    # centering - str.center() only pads, never shrinks, so
                    # a long name would otherwise spill past the bar uncut.
                    text = name[:barWidth].center(barWidth)
                else:
                    # Past the end of `entries` - blank, same as an empty inventory slot.
                    text = " " * barWidth
                    attr = defaultAttr
                _writeLine(pad, screenRow, screenCol, text, barWidth, attr)


def resolveEnterButtonClick(layout: PanelLayout, mouseRow: int, mouseCol: int) -> bool:
    row = _contentStartRow(layout) + _ENTER_ROW_OFFSET
    if mouseRow != row:
        return False
    colStart = centeredCol(layout, len(_ENTER_BUTTON_TEXT))
    colEnd = colStart + len(_ENTER_BUTTON_TEXT)
    return colStart <= mouseCol < colEnd


def resolveCycleButtonClick(layout: PanelLayout, widgetKind: str, mouseRow: int, mouseCol: int) -> bool:
    startRow = _contentStartRow(layout)
    if widgetKind == "portal":
        row = startRow + _PORTAL_CYCLE_ROW_OFFSET
    elif widgetKind == "bag":
        row = startRow + _BAG_LABEL_ROW_OFFSET
    else:
        return False
    _, colStart, colEnd = _cycleButtonRect(layout, row)
    return mouseRow == row and colStart <= mouseCol < colEnd


def resolveBagClick(layout: PanelLayout, mouseRow: int, mouseCol: int) -> Optional[int]:
    gridStartRow, rowStride = _bagGridRowStartAndStride(layout)
    cellWidth, colStride = _cellWidthAndStride(layout.panelWidth)

    relCol = mouseCol - layout.panelStartCol
    if relCol < 0 or relCol >= layout.panelWidth:
        return None

    rowOffset = mouseRow - gridStartRow
    if rowOffset < 0:
        return None
    row, rowRemainder = divmod(rowOffset, rowStride)
    if row >= _BAG_GRID_ROWS or rowRemainder != 0:
        return None  # between two grid rows (a divider row), not on one

    col, colOffsetWithinCell = divmod(relCol, colStride)
    if col >= _BAG_GRID_COLS or colOffsetWithinCell >= cellWidth:
        return None  # inside a gap/divider column, not a cell

    slotIndex = row * _BAG_GRID_COLS + col
    if slotIndex >= _BAG_SLOT_COUNT:
        return None
    return slotIndex
