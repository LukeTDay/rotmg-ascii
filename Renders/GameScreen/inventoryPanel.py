import curses
from typing import Optional, Tuple

from Constants import ColorPairs
from Constants.ItemGlyphs import resolveEquipmentChar, resolvePotionChar
from Models.PlayerData import PlayerData
from Renders.GameScreen.uiPanel import PanelLayout, drawGridDividers
from Utils.json.objectNameLoader import objectRenderInfo

# Same bar look as the HUD this replaced (mapRenderer.py's old
# _drawBar/_drawSolidBar/_drawHud) - relocated here since this module now
# owns the whole middle panel section (bars + inventory grid), not just a
# fixed 24-column right-side strip.
BAR_WIDTH = 20
# Fame/XP row, then HP+MP sharing one row (not two) - half-width each, side
# by side - to leave more vertical room for the inventory grid below.
_BAR_ROW_OFFSETS = (0, 2)
# Level at which XP stops mattering (no further levels) and the display
# switches back to Fame - RotMG's real level cap.
MAX_LEVEL = 20

BASE_INV_SLOTS = 12  # player.inv[0:12] - INVENTORY0..11STAT, always rendered
# player.inv[12:28] - BACKPACK0..15STAT, rendered per player.backpackSlots.
# StatTypes.py defines all 16 backpack stat ids (a character can have more
# than the original 8-slot backpack unlocked - confirmed live, e.g. a
# 12-slot backpack for 24 total inventory slots) - capped here at the full
# 16 StatTypes.py actually defines, not an arbitrary lower guess.
MAX_BACKPACK_SLOTS = 16
GRID_COLS = 4
TOTAL_SLOTS = BASE_INV_SLOTS + MAX_BACKPACK_SLOTS  # 28 - the grid always shows every possible slot, not just currently-unlocked ones
GRID_ROWS = TOTAL_SLOTS // GRID_COLS  # 7 - fixed, so the grid always fills the middle section rather than sizing to whatever's currently unlocked
MIN_CELL_WIDTH = 1
CELL_GAP = 1  # column between cells - doubles as the divider column, see drawInventoryGrid
# First row after the bars, with 1 blank row of spacing below the last one -
# the grid's own top bound; _gridRowStartAndStride spreads its rows from here
# down to the middle section's bottom edge.
_GRID_TOP_OFFSET = _BAR_ROW_OFFSETS[-1] + 2

# ObjectRenderInfo.bagColorTier's values are already curses color-name
# strings ("YELLOW"/"MAGENTA"/"BLUE"/"RED"/"WHITE" - see
# Scripts/AssetPipeline/deriveRenderInfo.py's _BAG_COLOR_REFERENCES/
# _TIER_COLOR_CUTOFFS, confirmed by reading that module directly rather than
# guessing), i.e. exactly ColorPairs.MAP_COLOR_TO_PAIR's own key vocabulary -
# reused as-is instead of inventing a second color-name mapping here.


def _drawBar(pad: curses.window, row: int, col: int, label: str, current: int, maximum: int,
             fillPair: int, emptyPair: int, width: int = BAR_WIDTH) -> None:
    """Old-school RPG bar: the label/numbers are centered *inside* the bar
    itself rather than beside it - black text over a solid color background
    where the bar is filled (`fillPair`), the same stat color as plain text
    on the default background where it isn't (`emptyPair`). Moved verbatim
    from mapRenderer.py's old _drawBar."""
    filled = 0 if maximum <= 0 else round(width * max(0, min(current, maximum)) / maximum)
    filled = max(0, min(width, filled))
    text = f"{label} {current}/{maximum}"[:width].center(width)
    try:
        if filled > 0:
            pad.addstr(row, col, text[:filled], curses.color_pair(fillPair))
        if filled < width:
            pad.addstr(row, col + filled, text[filled:], curses.color_pair(emptyPair))
    except curses.error:
        pass


def _drawSolidBar(pad: curses.window, row: int, col: int, value: int,
                   fillPair: int, width: int = BAR_WIDTH) -> None:
    """Same box look as _drawBar, but always fully "filled" - for a stat like
    fame that has no reliable max to be proportional against. Black text
    (just the number, no label/max) over a solid color background across
    the whole box. Moved verbatim from mapRenderer.py's old _drawSolidBar."""
    text = str(value)[:width].center(width)
    try:
        pad.addstr(row, col, text, curses.color_pair(fillPair))
    except curses.error:
        pass


def _contentStartRow(layout: PanelLayout) -> int:
    """First usable row inside the middle section, just below its top
    section-divider row (drawn by uiPanel.drawPanelFrame)."""
    return layout.middleSection.startRow + 1


def _cellWidthAndStride(panelWidth: int) -> Tuple[int, int]:
    """Cell width always fills a quarter of the panel (GRID_COLS is fixed at
    4, so the 3 gap/divider columns naturally land at exactly panelWidth's
    1/4, 1/2, and 3/4 marks) - grows unbounded with the panel, no longer
    capped, so a wider terminal actually produces a wider grid instead of
    leaving the extra width blank. stride = cellWidth + CELL_GAP; the gap
    column doubles as a vertical divider (see drawInventoryGrid). Falls back
    to the tightest possible 1-char/no-gap layout on the rare terminal too
    narrow to fit GRID_COLS cells any other way."""
    cellWidth = max(MIN_CELL_WIDTH, (panelWidth - (GRID_COLS - 1) * CELL_GAP) // GRID_COLS)
    stride = cellWidth + CELL_GAP
    neededForCurrent = GRID_COLS * stride - CELL_GAP  # no trailing gap after the last column
    if panelWidth >= neededForCurrent:
        return cellWidth, stride
    return 1, 1


def _gridRowStartAndStride(layout: PanelLayout) -> Tuple[int, int]:
    """Spreads all GRID_ROWS rows evenly across the full space between
    just-below-the-bars and the middle section's own bottom edge - unlike
    uiPanel.evenlySpacedRows (shared by bottomPanel's low-row-count grids,
    where an uncapped stride would look like one giant broken gap), GRID_ROWS
    is a fixed 7 here, large enough that spreading it across the whole
    section reads as an actual grid rather than sparse rows."""
    topBound = _contentStartRow(layout) + _GRID_TOP_OFFSET
    bottomBound = layout.middleSection.startRow + layout.middleSection.height - 1
    span = max(0, bottomBound - topBound)
    stride = max(1, span // (GRID_ROWS - 1))
    return topBound, stride


def drawBars(pad: curses.window, layout: PanelLayout, player: PlayerData) -> None:
    """Anchors the HP/MP/(XP-or-Fame) bars to the top of the panel's middle
    section, stretched to the panel's FULL width rather than a small fixed-
    width centered bar - relocated from mapRenderer.py's old _drawHud (which
    anchored to a fixed 24-column right-side strip; the whole right side is
    the panel now, so the bars use all of it). Fame/XP spans the entire
    panel width edge to edge; HP and MP share the row below it (not two
    separate rows) with HP stretched across the left half and MP across the
    right half, per user request. Below level 20, shows XP progress (WHITE
    bar, player.xp/player.nextLevelXp) instead of Fame, since XP is the more
    relevant "progress" stat while still leveling. At/after level 20 XP no
    longer increases, so this falls back to the old Fame solid-bar behavior
    unchanged: nextClassQuestFame is -1 whenever a class has no further
    quest reward, so Fame can't reliably be used as a proportional bar's max
    either - same reasoning the original _drawHud comment gave.
    """
    row = _contentStartRow(layout)
    col = layout.panelStartCol
    fullWidth = max(1, layout.panelWidth)

    if player.level < MAX_LEVEL:
        _drawBar(pad, row + _BAR_ROW_OFFSETS[0], col, f"LVL {player.level}", player.xp, player.nextLevelXp,
                 ColorPairs.FILL_WHITE, ColorPairs.MAP_WHITE, fullWidth)
    else:
        _drawSolidBar(pad, row + _BAR_ROW_OFFSETS[0], col, player.fame, ColorPairs.FILL_YELLOW, fullWidth)

    # HP and MP share one row (not two, like the old HUD) - HP stretched
    # across the left half, MP across the right half - to leave more
    # vertical room for the inventory grid below, especially now that a
    # character can have up to 16 backpack slots (7 grid rows) instead of
    # the old 8-slot cap.
    hpMpRow = row + _BAR_ROW_OFFSETS[1]
    hpWidth = max(1, fullWidth // 2)
    mpWidth = max(1, fullWidth - hpWidth)
    _drawBar(pad, hpMpRow, col, "HP", player.hp, player.maxHp,
             ColorPairs.FILL_RED, ColorPairs.MAP_RED, hpWidth)
    _drawBar(pad, hpMpRow, col + hpWidth, "MP", player.mp, player.maxMp,
             ColorPairs.FILL_BLUE, ColorPairs.MAP_BLUE, mpWidth)


def _cellContent(objectType: int, cellWidth: int) -> Tuple[str, int]:
    if objectType == -1:
        return " " * cellWidth, ColorPairs.MAP_WHITE
    info = objectRenderInfo(objectType)
    if info is None:
        return "?".center(cellWidth), ColorPairs.MAP_WHITE

    weaponLabel = getattr(info, "weaponLabel", "") or ""

    # Potions get their own char/color (h/m/c, red/blue/magenta) - overrides
    # the usual tier-based coloring.
    potion = resolvePotionChar(info.name or "", weaponLabel)
    if potion is not None:
        char, colorName = potion
        pairNum = ColorPairs.MAP_COLOR_TO_PAIR.get(colorName, ColorPairs.MAP_WHITE)
        return char.center(cellWidth), pairNum

    tier = getattr(info, "bagColorTier", "WHITE")
    pairNum = ColorPairs.MAP_COLOR_TO_PAIR.get(tier, ColorPairs.MAP_WHITE)

    equipChar = resolveEquipmentChar(weaponLabel)
    if equipChar is not None:
        return equipChar.center(cellWidth), pairNum

    # Unrecognized category - fall back to a name abbreviation.
    name = info.name.upper() if info.name else "?"
    return name[:cellWidth].center(cellWidth), pairNum


def drawInventoryGrid(pad: curses.window, layout: PanelLayout, player: PlayerData) -> None:
    """Draws the full 28-box (GRID_ROWS x GRID_COLS) inventory grid, always -
    spanning the whole middle section below the bars regardless of how many
    backpack slots are actually unlocked (see _gridRowStartAndStride/
    _cellWidthAndStride, both uncapped so the grid genuinely scales with a
    bigger panel instead of stopping once content fits).

    player.inv is always allocated at the full 28 slots (see
    Models/PlayerData.py), with not-yet-unlocked backpack slots simply
    holding -1 - so every box can always be drawn directly from player.inv,
    with locked slots rendering as blank (see _cellContent) rather than
    needing to be skipped.

    Each occupied cell shows as much of the item's name as the panel's
    width allows (see _cellWidthAndStride), colored by its bagColorTier
    bucket, with divider characters between cells/rows so an empty slot
    reads as empty rather than blending into the surrounding gap.
    """
    rowStart, rowStride = _gridRowStartAndStride(layout)
    cellWidth, colStride = _cellWidthAndStride(layout.panelWidth)
    gridStartCol = layout.panelStartCol

    drawGridDividers(pad, gridStartCol, rowStart, rowStride, colStride, CELL_GAP, GRID_ROWS, GRID_COLS)

    for i in range(TOTAL_SLOTS):
        row, col = divmod(i, GRID_COLS)
        screenRow = rowStart + row * rowStride
        screenCol = gridStartCol + col * colStride
        text, pairNum = _cellContent(player.inv[i], cellWidth)
        try:
            pad.addstr(screenRow, screenCol, text, curses.color_pair(pairNum))
        except curses.error:
            pass


def resolveInventoryClick(layout: PanelLayout, mouseRow: int, mouseCol: int,
                           backpackSlots: int = 0) -> Optional[int]:
    """The panel-space equivalent of mapRenderer.screenToWorld: converts a
    mouse event's screen row/col into an inventory slot index (0-27),
    returning None if the click falls outside the grid entirely (including a
    click that lands exactly on a divider rather than a cell) or lands on a
    box beyond backpackSlots - the grid itself is always fully drawn (see
    drawInventoryGrid), but a not-yet-unlocked backpack slot stays
    non-interactive even though its blank box is visible.
    """
    clampedBackpackSlots = max(0, min(MAX_BACKPACK_SLOTS, backpackSlots))
    totalSlots = BASE_INV_SLOTS + clampedBackpackSlots
    rowStart, rowStride = _gridRowStartAndStride(layout)
    cellWidth, colStride = _cellWidthAndStride(layout.panelWidth)

    relCol = mouseCol - layout.panelStartCol
    if relCol < 0 or relCol >= layout.panelWidth:
        return None

    rowOffset = mouseRow - rowStart
    if rowOffset < 0:
        return None
    row, rowRemainder = divmod(rowOffset, rowStride)
    if row >= GRID_ROWS or rowRemainder != 0:
        return None  # between two grid rows (a divider row), not on one

    col, colOffsetWithinCell = divmod(relCol, colStride)
    if col >= GRID_COLS or colOffsetWithinCell >= cellWidth:
        return None  # inside a gap/divider column, not a cell

    slotIndex = row * GRID_COLS + col
    if slotIndex >= totalSlots:
        return None
    return slotIndex
