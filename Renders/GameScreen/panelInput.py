import curses
import queue
import time
from typing import Optional, Set, Tuple

import Networking.PacketHelper as PacketHelper
from Models.Context import Context, SelectedSlot
from Models.GameState import GameState
from Models.PlayerData import PlayerData
from Networking.Listener import Listener
from Networking.Ticker import Ticker
from Renders.GameScreen import bottomPanel, inventoryPanel
from Renders.GameScreen.bottomPanel import _bagInventory
from Renders.GameScreen.itemInfoPeek import resolveClickedObject
from Renders.GameScreen.mapRenderer import screenToWorld
from Renders.GameScreen.uiPanel import PanelLayout


# A pending selection (first click of a swap/drop) with no second click
# within this many seconds gets dropped rather than staying armed
# indefinitely for some much-later, unrelated click - hand-tunable.
SELECTION_TIMEOUT_SECONDS = 3.0


def _isClick(bstate: int) -> bool:
    # BUTTON1_PRESSED as a fallback since not every terminal reports
    # BUTTON1_CLICKED reliably - same caveat noted for other mouse-button
    # handling in this codebase's design plan.
    return bool(bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED))


def _sendInvSwap(outgoingQueue: "queue.Queue", ticker: Ticker, a: SelectedSlot, b: SelectedSlot) -> None:
    packet = PacketHelper.createPacket("INVSWAP")
    packet.time = int(time.time() * 1000) - ticker.connectedTime
    packet.pos = ticker.pos.clone()
    packet.slotObject1.objectId = a.containerId
    packet.slotObject1.slotId = a.slotId
    packet.slotObject1.objectType = a.objectType
    packet.slotObject2.objectId = b.containerId
    packet.slotObject2.slotId = b.slotId
    packet.slotObject2.objectType = b.objectType
    outgoingQueue.put(packet)


def _sendInvDrop(outgoingQueue: "queue.Queue", slot: SelectedSlot) -> None:
    """Networking/Packets/Outgoing/InvDropPacket.py: just the dropped slot
    (objectId/slotId/objectType, same SlotObjectData shape INVSWAP's own
    sides use) plus an unknownByte this repo has no confirmed real-client
    value for - left at the class's own default (-1) rather than guessing."""
    packet = PacketHelper.createPacket("INVDROP")
    packet.slotObject.objectId = slot.containerId
    packet.slotObject.slotId = slot.slotId
    packet.slotObject.objectType = slot.objectType
    outgoingQueue.put(packet)


def _handleSlotClick(ctx: Context, outgoingQueue: "queue.Queue", ticker: Ticker,
                      containerId: int, slotId: int, objectType: int) -> None:
    """A click on an inventory or bag slot (player inventory grid or the
    bottom-panel bag grid - both funnel through here) does two things: sets
    the item-info peek to whatever's in that slot (if anything), and drives
    the select/second-click-to-swap flow. A second click on a DIFFERENT slot
    sends INVSWAP; a second click on the SAME slot just clears the selection
    (a same-slot swap would be a no-op anyway)."""
    if objectType != -1:
        ctx["PEEKED_OBJECT_TYPE"] = objectType
        # An inventory/bag slot's item has no live GameObject/objectId of its
        # own (it's not placed in the world) - clears any map-click peek's id
        # so itemInfoPeek.py doesn't show a stray live HP reading against it.
        ctx["PEEKED_OBJECT_ID"] = None

    clicked = SelectedSlot(containerId=containerId, slotId=slotId, objectType=objectType, selectedAt=time.time())
    selected = ctx.get("SELECTED_SLOT")

    if selected is None:
        if objectType == -1:
            return  # nothing to select on an empty slot with no prior selection
        ctx["SELECTED_SLOT"] = clicked
        return

    if selected.containerId == clicked.containerId and selected.slotId == clicked.slotId:
        ctx["SELECTED_SLOT"] = None
        return

    if ticker.pos is not None:
        _sendInvSwap(outgoingQueue, ticker, selected, clicked)
    ctx["SELECTED_SLOT"] = None


def handlePanelInput(mouseEvent: Optional[Tuple[int, int, int]], stdscr: curses.window, ctx: Context,
                      layout: PanelLayout, player: PlayerData, state: GameState, ticker: Ticker,
                      listener: Listener, outgoingQueue: "queue.Queue", projectileMap,
                      friendsList: Set[str], guildMembers: Set[str], lockedAccounts: Set[str]) -> None:
    """Routes this frame's single pre-fetched mouse event (see
    movementInput.getFrameMouseEvent - the SAME event handleShootInput also
    consumes, never a second curses.getmouse() call) to whichever area of
    the screen it landed in: the map area sets the item-info peek via
    resolveClickedObject, the panel dispatches by section (middle =
    inventory grid, bottom = whichever widget bottomPanel.resolveActiveWidget
    says is currently active - top section is read-only, nothing to do
    there).

    Runs the pending-selection timeout check (see SELECTION_TIMEOUT_SECONDS)
    unconditionally every frame, before the mouseEvent-is-None early return -
    a stale selection expires on its own after the timeout even if no
    further click ever arrives, not just "on the next click that happens to
    come in".
    """
    selected = ctx.get("SELECTED_SLOT")
    if selected is not None and time.time() - selected.selectedAt > SELECTION_TIMEOUT_SECONDS:
        ctx["SELECTED_SLOT"] = None

    if mouseEvent is None:
        return
    mouseRow, mouseCol, bstate = mouseEvent
    if not _isClick(bstate):
        return

    if mouseCol < layout.dividerCol:
        world = screenToWorld(stdscr, ticker, mouseRow, mouseCol)
        if world is None:
            return
        worldX, worldY = world
        obj = resolveClickedObject(state, listener.objectId, worldX, worldY, friendsList, guildMembers,
                                    lockedAccounts)
        ctx["PEEKED_OBJECT_TYPE"] = obj.objectType if obj is not None else None
        ctx["PEEKED_OBJECT_ID"] = obj.objectId if obj is not None else None
        return

    if mouseCol < layout.panelStartCol:
        return  # landed exactly on the vertical divider column - nothing to click

    middleSection = layout.middleSection
    if middleSection.startRow <= mouseRow < middleSection.startRow + middleSection.height:
        slot = inventoryPanel.resolveInventoryClick(layout, mouseRow, mouseCol, player.backpackSlots)
        if slot is not None:
            _handleSlotClick(ctx, outgoingQueue, ticker, player.objectId, slot, player.inv[slot])
        return

    bottomSection = layout.bottomSection
    if bottomSection.startRow <= mouseRow < bottomSection.startRow + bottomSection.height:
        widget = bottomPanel.resolveActiveWidget(ctx, state, ticker, listener.objectId, friendsList, guildMembers,
                                                  lockedAccounts)

        hasCycle = len(widget.candidates) > 1
        if bottomPanel.resolveCycleButtonClick(layout, widget.kind, hasCycle, mouseRow, mouseCol):
            if widget.candidates:
                ctx["BOTTOM_PANEL_CYCLE_INDEX"] = (ctx.get("BOTTOM_PANEL_CYCLE_INDEX", 0) + 1) % len(
                    widget.candidates)
            return

        if widget.kind == "portal" and widget.selected is not None:
            if bottomPanel.resolveEnterButtonClick(layout, hasCycle, mouseRow, mouseCol):
                packet = PacketHelper.createPacket("USEPORTAL")
                packet.objectId = widget.selected.objectId
                outgoingQueue.put(packet)
            return

        if widget.kind == "bag" and widget.selected is not None:
            slotIndex = bottomPanel.resolveBagClick(layout, mouseRow, mouseCol)
            if slotIndex is not None:
                bagInv = _bagInventory(widget.selected)
                _handleSlotClick(ctx, outgoingQueue, ticker, widget.selected.objectId, slotIndex,
                                  bagInv[slotIndex])
            return

        if widget.kind == "default":
            # No bag/portal nearby (just the map-name/player-count default
            # widget) - clicking anywhere in the bottom section with a slot
            # already selected drops that item on the ground (INVDROP)
            # instead of doing nothing, per user request. Only fires with a
            # real pending selection - an idle click on the default widget
            # is still a no-op.
            selected = ctx.get("SELECTED_SLOT")
            if selected is not None:
                _sendInvDrop(outgoingQueue, selected)
                ctx["SELECTED_SLOT"] = None
            return
        return

    # Top section (item-info peek) is read-only - nothing clickable there.
