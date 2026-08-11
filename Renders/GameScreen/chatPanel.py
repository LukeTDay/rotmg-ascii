import curses
import textwrap
from collections import deque
from dataclasses import dataclass
from typing import List, Tuple

import Networking.PacketHelper as PacketHelper
from Constants import ColorPairs
from Models.Context import ChatMessage, Context
from Networking.Ticker import Ticker

# Fraction of the terminal's full width given to the left-side chat panel -
# the map area gets whatever's left between this and uiPanel's own right-side
# PANEL_WIDTH_FRACTION (see mapRenderer.computeScale, which imports this
# constant rather than duplicating it).
CHAT_PANEL_WIDTH_FRACTION = 0.33

# Vertical split of the panel's 2 stacked halves - top is an empty
# placeholder reserved for a future feature (system-message display etc,
# per user request - not wired up yet), bottom is the chat itself.
TOP_SECTION_FRACTION = 0.5

SECTION_DIVIDER_CHAR = "-"
VERTICAL_DIVIDER_CHAR = "|"

CHAT_KEY = ord("/")
MAX_MESSAGE_LENGTH = 128
MAX_HISTORY = 200

_KIND_TO_COLOR_NAME = {"self": "CYAN", "other": "WHITE", "world": "YELLOW"}

_TOP_PLACEHOLDER_TEXT = "(reserved)"
_IDLE_INPUT_TEXT = "Press / to chat"


@dataclass(frozen=True)
class ChatSection:
    startRow: int
    height: int


@dataclass(frozen=True)
class ChatLayout:
    """The chat panel's own layout, independent of uiPanel.PanelLayout (the
    right-side panel) - columns [0, dividerCol) are the panel's content,
    dividerCol is the vertical divider itself, mapStartCol (dividerCol + 1)
    is where mapRenderer's map area begins."""
    dividerCol: int
    mapStartCol: int
    panelWidth: int
    topSection: ChatSection
    bottomSection: ChatSection


def computeChatLayout(maxY: int, maxX: int) -> ChatLayout:
    """Mirrors uiPanel.computePanelLayout's formula shape, mirrored to the
    left edge instead of the right. Recomputed fresh every frame from the
    terminal's actual current size - never cached, so a resize is picked up
    on the very next frame."""
    panelWidth = max(1, round(maxX * CHAT_PANEL_WIDTH_FRACTION) - 1)
    dividerCol = panelWidth

    topHeight = max(1, round(maxY * TOP_SECTION_FRACTION))
    bottomHeight = max(1, maxY - topHeight)
    topSection = ChatSection(0, topHeight)
    bottomSection = ChatSection(topHeight, bottomHeight)

    return ChatLayout(
        dividerCol=dividerCol,
        mapStartCol=dividerCol + 1,
        panelWidth=panelWidth,
        topSection=topSection,
        bottomSection=bottomSection,
    )


def _bottomRows(layout: ChatLayout) -> Tuple[int, int, int]:
    """Returns (messageAreaStartRow, messageAreaEndRowExclusive, inputRow)
    within the bottom (chat) half: the last row is the input bar, the row
    just above it is a divider, everything above that (down to the
    top/bottom section boundary) is the message buffer."""
    bottom = layout.bottomSection
    inputRow = bottom.startRow + bottom.height - 1
    inputDividerRow = inputRow - 1
    messageStart = bottom.startRow + 1
    messageEnd = max(messageStart, inputDividerRow)
    return messageStart, messageEnd, inputRow


def _write(pad: curses.window, row: int, col: int, text: str, attr: int) -> None:
    try:
        pad.addstr(row, col, text, attr)
    except curses.error:
        pass  # edge writes can fail - drop the write, not the frame


def drawChatFrame(pad: curses.window, layout: ChatLayout) -> None:
    attr = curses.color_pair(ColorPairs.DEFAULT)
    totalHeight = layout.topSection.height + layout.bottomSection.height
    for row in range(totalHeight):
        _write(pad, row, layout.dividerCol, VERTICAL_DIVIDER_CHAR, attr)

    _write(pad, layout.bottomSection.startRow, 0, SECTION_DIVIDER_CHAR * layout.panelWidth, attr)

    messageStart, messageEnd, inputRow = _bottomRows(layout)
    if inputRow - 1 > messageEnd - 1:
        # Only draw the message/input divider if there's actually a distinct
        # row for it (a very short terminal can collapse them together).
        _write(pad, inputRow - 1, 0, SECTION_DIVIDER_CHAR * layout.panelWidth, attr)


def _drawTopPlaceholder(pad: curses.window, layout: ChatLayout) -> None:
    top = layout.topSection
    row = top.startRow + top.height // 2
    col = max(0, (layout.panelWidth - len(_TOP_PLACEHOLDER_TEXT)) // 2)
    _write(pad, row, col, _TOP_PLACEHOLDER_TEXT[:layout.panelWidth], curses.color_pair(ColorPairs.DEFAULT))


def _wrapMessages(ctx: Context, width: int) -> List[Tuple[str, int]]:
    history = ctx.get("CHAT_MESSAGES")
    if not history:
        return []
    lines: List[Tuple[str, int]] = []
    for msg in history:
        prefix = "" if msg.kind == "world" else f"{msg.sender}: "
        pairNum = ColorPairs.MAP_COLOR_TO_PAIR[_KIND_TO_COLOR_NAME[msg.kind]]
        for line in textwrap.wrap(prefix + msg.text, max(1, width)) or [""]:
            lines.append((line, pairNum))
    return lines


def _drawMessages(pad: curses.window, layout: ChatLayout, ctx: Context) -> None:
    messageStart, messageEnd, _ = _bottomRows(layout)
    rowCount = messageEnd - messageStart
    if rowCount <= 0:
        return
    visible = _wrapMessages(ctx, layout.panelWidth)[-rowCount:]
    startRow = messageEnd - len(visible)
    for i, (text, pairNum) in enumerate(visible):
        _write(pad, startRow + i, 0, text[:layout.panelWidth], curses.color_pair(pairNum))


def _drawInputBar(pad: curses.window, layout: ChatLayout, ctx: Context) -> None:
    _, _, inputRow = _bottomRows(layout)
    typing = ctx.get("CHAT_TYPING", False)

    if not typing:
        _write(pad, inputRow, 0, _IDLE_INPUT_TEXT[:layout.panelWidth], curses.color_pair(ColorPairs.DEFAULT))
        return

    buffer = ctx.get("CHAT_INPUT", "")
    prefix = "> "
    # Cursor always visible: shows the tail of the buffer once it outgrows
    # the visible width, rather than truncating from the end.
    available = max(1, layout.panelWidth - len(prefix) - 1)
    visibleBuffer = buffer[-available:] if len(buffer) > available else buffer
    text = f"{prefix}{visibleBuffer}_"
    padded = text[:layout.panelWidth].ljust(layout.panelWidth)
    # At the hard cap, every further keystroke is silently dropped (see
    # handleChatInput) - flip the bar red so that's visible, not silent.
    atCap = len(buffer) >= MAX_MESSAGE_LENGTH
    fillPair = ColorPairs.FILL_RED if atCap else ColorPairs.FILL_WHITE
    _write(pad, inputRow, 0, padded, curses.color_pair(fillPair))


def drawChatPanel(pad: curses.window, layout: ChatLayout, ctx: Context) -> None:
    drawChatFrame(pad, layout)
    _drawTopPlaceholder(pad, layout)
    _drawMessages(pad, layout, ctx)
    _drawInputBar(pad, layout, ctx)


def recordIncomingText(ctx: Context, event, selfObjectId: int) -> None:
    """Appends one incoming TEXT packet to the chat history. name=="" is a
    nameless/world message (e.g. a server announcement); otherwise it's a
    player message, colored differently depending on whether it's this
    client's own echoed-back message or someone else's."""
    history = ctx.setdefault("CHAT_MESSAGES", deque(maxlen=MAX_HISTORY))
    if event.name == "":
        kind = "world"
    elif event.objectId == selfObjectId:
        kind = "self"
    else:
        kind = "other"
    history.append(ChatMessage(kind=kind, sender=event.name, text=event.cleanText))


def _sendChatMessage(outgoingQueue, text: str) -> None:
    packet = PacketHelper.createPacket("PLAYERTEXT")
    # Hard cap enforced again here, on the packet itself, right before it's
    # queued - not just trusted from the input buffer's own cap (see
    # handleChatInput) - so this can never regress into sending an
    # oversized PLAYERTEXT even if some future change feeds this function a
    # string from somewhere else.
    packet.text = text[:MAX_MESSAGE_LENGTH]
    assert len(packet.text) <= MAX_MESSAGE_LENGTH, \
        f"PLAYERTEXT.text is {len(packet.text)} chars, over the {MAX_MESSAGE_LENGTH}-char hard cap"
    outgoingQueue.put(packet)


def handleChatInput(keys: List[int], ctx: Context, outgoingQueue, ticker: Ticker) -> bool:
    """Returns True if this frame's keys were consumed by the chat box (the
    caller should then skip movement/shoot input entirely for the frame) -
    true both on the frame '/' opens the box and every frame while it stays
    open. The "/" key stops movement immediately (per user request) by
    snapping Ticker's target to the current position.
    """
    typing = ctx.get("CHAT_TYPING", False)

    if not typing:
        if CHAT_KEY not in keys:
            return False
        ctx["CHAT_TYPING"] = True
        ctx["CHAT_INPUT"] = ""
        if ticker.pos is not None:
            ticker.setTarget(ticker.pos)
        return True

    for key in keys:
        if key in (curses.KEY_ENTER, 10, 13):
            message = ctx.get("CHAT_INPUT", "").strip()
            if message:
                _sendChatMessage(outgoingQueue, message)
            ctx["CHAT_TYPING"] = False
            ctx["CHAT_INPUT"] = ""
            return True
        elif key == 27:  # ESC - cancel without sending
            ctx["CHAT_TYPING"] = False
            ctx["CHAT_INPUT"] = ""
            return True
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            ctx["CHAT_INPUT"] = ctx.get("CHAT_INPUT", "")[:-1]
        elif 32 <= key <= 126:
            current = ctx.get("CHAT_INPUT", "")
            if len(current) < MAX_MESSAGE_LENGTH:
                ctx["CHAT_INPUT"] = current + chr(key)
            # else: silently drop - MAX_MESSAGE_LENGTH is a hard cap, never exceeded

    return True
