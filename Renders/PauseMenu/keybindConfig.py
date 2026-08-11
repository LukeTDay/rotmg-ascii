import curses
from typing import Dict, Optional

from Constants import ColorPairs
from Models.Context import Context, required
from Networking.PacketLogSettings import PacketLogSettings
from Renders.EnterAccountInfo.enterAccountInfo import (
    centeredX, determineRefreshWindow, drawCenteredBanner, drawCenteredText, drawTextAt, figletLineCount,
)
from Renders.GameScreen.inputRouter import NEXUS_MODE_FIELD, toggleNexusMode
from Renders.PauseMenu import debugOptions
from Renders.backgroundTexture import drawBackgroundTexture
from Utils.json.keybindLoader import saveKeybinds

ROWS_PER_SLOT = 2  # 1 text row + 1 blank spacer row

_TAB_GAMEPLAY = "gameplay"
_TAB_DEBUG = "debug"
_SWITCH_TO_DEBUG_LABEL = "Debug Options"
_SWITCH_TO_GAMEPLAY_LABEL = "Gameplay Settings"


def _normalizeKey(ch: str) -> str:
    # Matches inputRouter's own matching rules: letters compare
    # case-insensitively (both 'w' and 'W' hit the same binding), everything
    # else (e.g. '/') compares exactly.
    return ch.lower() if ch.isalpha() else ch


def _findConflict(keybinds: Dict[str, str], editingField: str, candidate: str) -> Optional[str]:
    """Returns the name of another field already bound to `candidate`, or
    None if it's free to use."""
    normalizedCandidate = _normalizeKey(candidate)
    for otherField, otherValue in keybinds.items():
        if otherField != editingField and _normalizeKey(otherValue) == normalizedCandidate:
            return otherField
    return None


def drawKeybindConfig(stdscr: curses.window, ctx: Context) -> None:
    """Nested screen reached from the pause menu's "Change Keybinds" entry -
    always returns to its caller (never touches Screen/main.py). Two tabs,
    GAMEPLAY (keybinds, edits ctx["KEYBINDS"] in place) and DEBUG (packet
    logging, edits ctx["PACKET_LOG_SETTINGS"] in place - see
    Renders/PauseMenu/debugOptions.py) - a switch row always sits at the
    bottom of whichever tab is showing. Each tab persists its own change
    immediately (saveKeybinds/saveDebugSettings), not on exit."""
    debugger = required(ctx.get("DEBUGGER"), "DEBUGGER")
    debugger.info("Entering keybind config screen")

    keybinds = ctx.setdefault("KEYBINDS", {})
    settings: PacketLogSettings = required(ctx.get("PACKET_LOG_SETTINGS"), "PACKET_LOG_SETTINGS")
    gameplayFields = list(keybinds.keys())
    debugNames = debugOptions.packetNames()
    if not gameplayFields:
        return

    pad = curses.newpad(max(200, debugOptions.rowCount(debugNames) + 20), 500)
    pad.keypad(True)

    headerHeight = figletLineCount("CONFIG") + 1

    tab = _TAB_GAMEPLAY
    selected = 0
    scrollOffset = 0
    selectionChanged = False
    editing = False
    pendingValue = ""
    conflictField: Optional[str] = None
    conflictChar = ""

    while True:
        pad.move(0, 0)
        pad.clrtobot()
        drawBackgroundTexture(stdscr, pad, ctx, forceRegen=selectionChanged)

        height, _width = stdscr.getmaxyx()
        rowCount = (len(gameplayFields) if tab == _TAB_GAMEPLAY else debugOptions.rowCount(debugNames)) + 1
        switchRow = rowCount - 1
        visibleRows = max(1, (height - headerHeight) // ROWS_PER_SLOT)

        if selected < scrollOffset:
            scrollOffset = selected
        elif selected >= scrollOffset + visibleRows:
            scrollOffset = selected - visibleRows + 1

        shownCount = min(visibleRows, rowCount - scrollOffset)
        totalHeight = headerHeight + shownCount * ROWS_PER_SLOT + 1
        y = max(0, (height - totalHeight) // 2)

        y = drawCenteredBanner(stdscr, pad, y, "CONFIG")
        y += 1

        for row in range(scrollOffset, min(scrollOffset + visibleRows, rowCount)):
            isSelectedRow = row == selected
            isEditingRow = isSelectedRow and editing
            if isEditingRow:
                attr = curses.color_pair(ColorPairs.CRUCIBLE_SELECTED)
            elif isSelectedRow:
                attr = curses.A_REVERSE
            else:
                attr = curses.A_NORMAL

            if row == switchRow:
                label = _SWITCH_TO_DEBUG_LABEL if tab == _TAB_GAMEPLAY else _SWITCH_TO_GAMEPLAY_LABEL
                y = drawCenteredText(stdscr, pad, y, label, attr)
                y += 1
            elif tab == _TAB_GAMEPLAY:
                field = gameplayFields[row]
                value = pendingValue if isEditingRow else keybinds[field]
                # Fixed per-row x, computed from the prompt alone (not the
                # value) - drawn via drawTextAt instead of drawCenteredText, so
                # the row doesn't recenter/shift as the typed value grows from
                # empty to a character while editing.
                prompt = f"{field}: "
                x = centeredX(stdscr, prompt)
                y = drawTextAt(stdscr, pad, y, x, f"{prompt}{value}", attr)
                y += 1
            else:
                label = debugOptions.rowLabel(row, debugNames, settings)
                y = drawCenteredText(stdscr, pad, y, label, attr)
                y += 1

        if conflictField is not None:
            instructions = f"'{conflictChar}' is already used by {conflictField} - press a different key"
        elif editing:
            instructions = "Press a key, then Enter to confirm (ESC to cancel)"
        else:
            instructions = "ESC to go back, Enter to change/toggle"
        y = drawCenteredText(stdscr, pad, y, instructions)
        determineRefreshWindow(stdscr, pad, y)

        key = pad.getch()

        if editing:
            if key == 27:
                editing = False
                pendingValue = ""
                conflictField = None
            elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                if pendingValue:
                    field = gameplayFields[selected]
                    keybinds[field] = pendingValue
                    saveKeybinds(keybinds)
                    debugger.info(f"Keybind {field!r} set to {pendingValue!r}")
                editing = False
                pendingValue = ""
                conflictField = None
            elif 32 <= key <= 126:
                # A single printable character - the most recent keystroke
                # this edit wins, matching every other key-matching site in
                # the app comparing single ord() values (arrows/function
                # keys stay fixed, never reach this branch). Rejected if
                # another field already uses it - pendingValue (and thus the
                # displayed row) is left untouched, so the user just keeps
                # seeing the conflict message until they press a free key.
                candidate = chr(key)
                conflict = _findConflict(keybinds, gameplayFields[selected], candidate)
                if conflict is not None:
                    conflictField = conflict
                    conflictChar = candidate
                else:
                    pendingValue = candidate
                    conflictField = None
            continue

        if key == 27:
            return

        prevSelected = selected
        if key == curses.KEY_UP or key == ord('w'):
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN or key == ord('s'):
            selected = min(rowCount - 1, selected + 1)
        selectionChanged = selected != prevSelected

        if key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            if selected == switchRow:
                tab = _TAB_DEBUG if tab == _TAB_GAMEPLAY else _TAB_GAMEPLAY
                selected = 0
                scrollOffset = 0
                selectionChanged = True
                pendingValue = ""
                conflictField = None
            elif tab == _TAB_GAMEPLAY:
                field = gameplayFields[selected]
                if field == NEXUS_MODE_FIELD:
                    # A 2-value enum, not a single keystroke - Enter just flips
                    # it and saves immediately, no edit sub-state needed.
                    newMode = toggleNexusMode(keybinds)
                    saveKeybinds(keybinds)
                    debugger.info(f"Nexus mode set to {newMode!r}")
                else:
                    editing = True
                    pendingValue = ""
                    conflictField = None
            else:
                debugOptions.activate(selected, debugNames, settings, debugger)
