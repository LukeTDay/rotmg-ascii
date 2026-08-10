import curses
from dataclasses import dataclass
from typing import Tuple

from Constants import ColorPairs

# Fraction of the terminal's full width given to the right-side UI panel -
# the map area gets whatever's left (see mapRenderer.computeScale, which
# imports this constant rather than duplicating it). Hand-tuned, easy to
# adjust.
PANEL_WIDTH_FRACTION = 0.33

# Horizontal dividers between the panel's 3 stacked sections.
SECTION_DIVIDER_CHAR = "-"
# Single column separating the map area from the whole panel - drawn full
# terminal height, not just implicit blank space.
VERTICAL_DIVIDER_CHAR = "|"

# Vertical split of the panel's 3 stacked sections (top/middle/bottom),
# as fractions of the full terminal height. Must sum to 1.0.
TOP_SECTION_FRACTION = 0.25
MIDDLE_SECTION_FRACTION = 0.50
BOTTOM_SECTION_FRACTION = 0.25


@dataclass(frozen=True)
class PanelSection:
    """One vertically-stacked slice of the panel. `startRow`/`height` are in
    the same pad-row coordinate space as everything else this screen draws
    in - a section's usable rows are `range(startRow, startRow + height)`."""
    startRow: int
    height: int


@dataclass(frozen=True)
class PanelLayout:
    """Returned by computePanelLayout - the single shared shape every panel-
    drawing module (inventoryPanel.py today, top/bottom-section modules in a
    follow-up phase) builds against, so a terminal-size change only needs to
    be handled in one place.

    `dividerCol` is both "the last column of the map area" (exclusive) and
    "the column the vertical divider itself is drawn in" - mapRenderer's
    mapAreaCols is computed with the exact same formula, so the two always
    agree on where the boundary is.
    """
    dividerCol: int
    panelStartCol: int
    panelWidth: int
    topSection: PanelSection
    middleSection: PanelSection
    bottomSection: PanelSection


def computePanelLayout(maxY: int, maxX: int) -> PanelLayout:
    """Partitions the terminal into the map/panel boundary column and the
    panel's 3 stacked sections (25%/50%/25% of the full terminal height).
    Recomputed fresh every frame from the terminal's actual current size
    (same convention as mapRenderer.computeScale) - never cached, so a
    terminal resize is picked up on the very next frame.
    """
    dividerCol = maxX - round(maxX * PANEL_WIDTH_FRACTION)
    panelStartCol = dividerCol + 1
    # -1 reserves the divider column itself so it doesn't eat into usable
    # panel width.
    panelWidth = max(1, round(maxX * PANEL_WIDTH_FRACTION) - 1)

    topHeight = max(1, round(maxY * TOP_SECTION_FRACTION))
    middleHeight = max(1, round(maxY * MIDDLE_SECTION_FRACTION))
    # Bottom gets the remainder rather than its own round() call, so the 3
    # sections always sum to exactly maxY (no gap/overlap from independent
    # rounding) even at small terminal heights.
    bottomHeight = max(1, maxY - topHeight - middleHeight)

    topSection = PanelSection(0, topHeight)
    middleSection = PanelSection(topHeight, middleHeight)
    bottomSection = PanelSection(topHeight + middleHeight, bottomHeight)

    return PanelLayout(
        dividerCol=dividerCol,
        panelStartCol=panelStartCol,
        panelWidth=panelWidth,
        topSection=topSection,
        middleSection=middleSection,
        bottomSection=bottomSection,
    )


def drawPanelFrame(pad: curses.window, layout: PanelLayout) -> None:
    """Draws the vertical map/panel divider (full terminal height) and the
    two horizontal section dividers (spanning panelWidth, at the top/middle
    and middle/bottom section boundaries). Called once per frame from
    gameScreen.py's _connectedLoop, right after mapRenderer.drawFrame, before
    the pad gets blitted.
    """
    attr = curses.color_pair(ColorPairs.DEFAULT)
    totalHeight = layout.topSection.height + layout.middleSection.height + layout.bottomSection.height

    for row in range(totalHeight):
        try:
            pad.addstr(row, layout.dividerCol, VERTICAL_DIVIDER_CHAR, attr)
        except curses.error:
            # Bottom-right corner writes are more failure-prone than the
            # rest of a line (see mapRenderer._drawMap's identical pattern) -
            # drop the write, not the frame.
            pass

    dividerLine = SECTION_DIVIDER_CHAR * layout.panelWidth
    for boundaryRow in (layout.middleSection.startRow, layout.bottomSection.startRow):
        try:
            pad.addstr(boundaryRow, layout.panelStartCol, dividerLine, attr)
        except curses.error:
            pass


def centeredCol(layout: PanelLayout, textLen: int) -> int:
    """Horizontal start column to center a `textLen`-wide piece of text
    within the panel's own width - not the whole terminal (see
    Renders/EnterAccountInfo/enterAccountInfo.py's drawCenteredText/
    centeredX for the whole-terminal equivalent the menu screens use, which
    doesn't apply here since the panel is only ~1/3 of the terminal width).
    """
    return layout.panelStartCol + max(0, (layout.panelWidth - textLen) // 2)


def drawGridDividers(pad: curses.window, gridStartCol: int, rowStart: int, rowStride: int, colStride: int,
                      cellGap: int, rowCount: int, gridCols: int) -> None:
    """Draws a divider column between each pair of adjacent cells (every
    drawn grid row) and a divider line between each pair of adjacent grid
    rows (only when rowStride actually leaves a blank row to draw one in) -
    "make it clear where empty slots are" per user request, since an empty
    cell is otherwise just blank space indistinguishable from the gap next
    to it. Shared by inventoryPanel's inventory grid and bottomPanel's bag
    grid so both use the same divider characters/logic."""
    attr = curses.color_pair(ColorPairs.DEFAULT)

    for gridCol in range(1, gridCols):
        dividerCol = gridStartCol + gridCol * colStride - cellGap
        for gridRow in range(rowCount):
            screenRow = rowStart + gridRow * rowStride
            try:
                pad.addstr(screenRow, dividerCol, VERTICAL_DIVIDER_CHAR, attr)
            except curses.error:
                pass

    if rowStride <= 1:
        return  # no blank row between grid rows to draw a horizontal divider in
    lineWidth = gridCols * colStride - cellGap
    dividerLine = SECTION_DIVIDER_CHAR * lineWidth
    for gridRow in range(rowCount - 1):
        dividerRow = rowStart + gridRow * rowStride + 1
        if dividerRow >= rowStart + (gridRow + 1) * rowStride:
            continue
        try:
            pad.addstr(dividerRow, gridStartCol, dividerLine, attr)
        except curses.error:
            pass


# Cap on the vertical gap between grid rows - 2 (one content row + one blank/
# divider row) is enough to visually separate rows without them reading as
# sparse/disconnected. A grid with few rows (e.g. the bag grid's fixed 2) in
# a tall section used to stretch to fill the *entire* remaining space with a
# single huge gap between rows, which looked broken rather than "pushed
# toward the end" - now any leftover space beyond what MAX_ROW_STRIDE needs
# is left as blank padding above the (still bottom-anchored) block of rows
# instead of being spread out as oversized inter-row gaps.
_MAX_ROW_STRIDE = 2


def evenlySpacedRows(topBound: int, bottomBound: int, rowCount: int) -> Tuple[int, int]:
    """Positions `rowCount` rows, each MAX_ROW_STRIDE pad-rows apart (capped -
    see _MAX_ROW_STRIDE), so the block's last row lands at (or just above)
    bottomBound - the whole block sits near the end of its section rather
    than packed tightly right below whatever's above it, without the rows
    themselves spreading out into oversized gaps. Returns (firstRowStart,
    stride) - row i of the grid is drawn/hit-tested at firstRowStart +
    i*stride. Shared by inventoryPanel's own inventory grid and bottomPanel's
    bag grid. Falls back to stride=1 starting at topBound if there's only
    one row or not enough room even for that.
    """
    if rowCount <= 1 or bottomBound <= topBound:
        return topBound, 1
    span = bottomBound - topBound
    stride = min(_MAX_ROW_STRIDE, max(1, span // (rowCount - 1)))
    rowStart = bottomBound - (rowCount - 1) * stride
    return max(topBound, rowStart), stride
