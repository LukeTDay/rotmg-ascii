from typing import TypedDict, List, Dict, FrozenSet, NamedTuple, Set, Tuple, TypeVar

from Models.CharListData import CharListData

from Networking.Ticker import Ticker
from Networking.Listener import Listener
from Networking.Sender import Sender
from Debug.Debugger import Debugger

import queue
import random


class AccountData(TypedDict):
    alias: str
    email: str
    password: str


class PendingReconnectHello(NamedTuple):
    """Set by gameScreen.py's _handleReconnect when a RECONNECT packet
    arrives (mid-handshake or mid-game) - the gameId/keyTime/key the next
    HELLO must carry instead of the normal fresh-login defaults (GameIds.
    nexus/0/[]). Consumed and cleared by _establishConnection on its next
    pass. Mirrors pyrelay's Client.onReconnect/connect (see CLAUDE.local.md's
    Reference projects) - a RECONNECT's gameId/key/keyTime replace whatever
    the client was previously using, unconditionally."""
    gameId: int
    keyTime: int
    key: List[int]


class SelectedSlot(NamedTuple):
    """A single selected inventory/bag slot, pending a second click to swap
    (or a bottom-panel-default click to drop) with - see
    Renders/GameScreen/panelInput.py's _handleSlotClick. `containerId` is the
    objectId that owns the slot: the local player's own objectId for the
    player inventory grid, or a loot bag's objectId for the bottom-panel bag
    grid - InvSwapPacket.slotObject{1,2}.objectId's exact meaning.
    `selectedAt` (time.time() when this became the pending selection) backs
    panelInput.py's selection-timeout expiry - a selection older than
    SELECTION_TIMEOUT_SECONDS with no second click gets dropped rather than
    staying armed indefinitely for some much-later, unrelated click."""
    containerId: int
    slotId: int
    objectType: int
    selectedAt: float


class Context(TypedDict, total=False):
    account: AccountData
    accessToken: str
    clientToken: str
    buildVersion: str
    CHARLIST: List[CharListData]
    FRIENDSLIST: Set[str]
    GUILDMEMBERS: Set[str]
    LOCKEDACCOUNTS: Set[str]
    SERVERS: Dict[str, str]
    CURR_CHAR_ID: int
    CURR_SERVER: str
    TICKER : Ticker
    LISTENER : Listener
    SENDER : Sender
    INCOMINGQUEUE : queue.Queue
    OUTGOINGQUEUE : queue.Queue
    DEBUGGER : Debugger
    RNG : random.Random
    TILE_CHAR_CACHE : Dict[Tuple[str, int, int, int], str]
    # The currently-selected inventory/bag slot awaiting a second click to
    # swap with (see Renders/GameScreen/panelInput.py's _handleSlotClick) -
    # None means nothing is selected. Set/cleared via direct assignment as
    # slots are clicked, read via ctx.get (unset until the first click).
    SELECTED_SLOT : SelectedSlot | None
    # The objectType currently shown in the top-panel item-info peek (see
    # Renders/GameScreen/itemInfoPeek.py) - raw id only, re-resolved via
    # objectRenderInfo/projectileMap fresh every frame, not a cached
    # name/stats snapshot (this codebase's "recompute derived display state
    # every frame" convention). None means nothing peeked yet.
    PEEKED_OBJECT_TYPE : int | None
    # Which candidate (portal or loot bag) the bottom panel (see
    # Renders/GameScreen/bottomPanel.py) is currently showing, when more than
    # one is in range - wraps via the panel's "next" button. Reset to 0
    # whenever BOTTOM_PANEL_CANDIDATE_IDS changes frame to frame (walked away
    # from one candidate set to a different one), so it never points at a
    # stale index.
    BOTTOM_PANEL_CYCLE_INDEX : int
    # The winning tier's candidate objectId set as of the last frame
    # bottomPanel.resolveActiveWidget ran - compared against the current
    # frame's set purely to detect when BOTTOM_PANEL_CYCLE_INDEX needs
    # resetting, not read for any other purpose.
    BOTTOM_PANEL_CANDIDATE_IDS : FrozenSet[int]
    # Set once in gameScreen.py's _handshake as soon as a MAPINFO/RECONNECT
    # names the current map - _handshake itself only holds this locally
    # otherwise and it'd be lost once that function returns. Read by
    # bottomPanel.py's default (no nearby portal/bag) widget.
    CURR_MAP_NAME : str
    # Set by gameScreen.py's _handleReconnect when a RECONNECT packet is
    # handled, popped by _establishConnection on its next pass to build the
    # follow-up HELLO's gameId/keyTime/key - see PendingReconnectHello. Absent
    # means the next HELLO is a normal fresh login (GameIds.nexus/0/[]).
    PENDING_RECONNECT_HELLO : PendingReconnectHello


T = TypeVar("T")


def required(value: T | None, name: str) -> T:
    """Narrow a ctx.get(...) result, asserting the earlier screen already set it.

    Context keys are optional in the type system (they're filled in progressively
    across screens), but by the time a given screen runs, specific keys are always
    present. Use this instead of ctx["key"] to get that guarantee back without
    silencing the TypedDict checker: required(ctx.get("account"), "account").
    """
    assert value is not None, f"ctx[{name!r}] should already be set at this point in the flow"
    return value
