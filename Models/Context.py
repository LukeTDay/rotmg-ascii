from typing import Deque, TypedDict, List, Dict, FrozenSet, NamedTuple, Set, Tuple, TypeVar

from Models.CharData import CharData
from Models.CharListData import CharListData
from Models.TileManager import PerTileIndex, RenderCell

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
    """Set by _handleReconnect on RECONNECT - the gameId/keyTime/key the next HELLO must carry."""
    gameId: int
    keyTime: int
    key: List[int]


class PendingNewChar(NamedTuple):
    """Set by charCreate.py once a class + seasonal/standard choice is confirmed -
    consumed wherever the actual CREATE packet ends up getting sent."""
    classType: int
    isSeasonal: bool


class SelectedSlot(NamedTuple):
    """A selected inventory/bag slot awaiting a second click to swap/drop - see panelInput.py."""
    containerId: int
    slotId: int
    objectType: int
    selectedAt: float


class ChatMessage(NamedTuple):
    """One line of chat history - see Renders/GameScreen/chatPanel.py.
    kind is "self" (this client's own message), "locked" (a locked account),
    "guild" (a guildmate), "other" (any other player), or "world" (a nameless
    TEXT packet/synthetic system message, e.g. a server announcement)."""
    kind: str
    sender: str
    text: str


class Context(TypedDict, total=False):
    account: AccountData
    accessToken: str
    clientToken: str
    buildVersion: str
    CHARLIST: List[CharListData]
    # nextCharId/maxNumChars/unlockedClasses derived from the same char/list
    # response CHARLIST comes from - see Utils/XML/parseCharList.parseCharData.
    CHARDATA: CharData
    FRIENDSLIST: Set[str]
    GUILDMEMBERS: Set[str]
    LOCKEDACCOUNTS: Set[str]
    SERVERS: Dict[str, str]
    CURR_CHAR_ID: int
    # Set instead of CURR_CHAR_ID when heading into serverSelect/gameScreen to
    # create a new character rather than load an existing one.
    PENDING_NEW_CHAR: PendingNewChar
    CURR_SERVER: str
    # The host picked in serverSelect.py, kept unchanged for the whole
    # session even as CURR_SERVER drifts to whatever realm/dungeon-specific
    # host each RECONNECT bounces to. Only a fresh connect to this original
    # host reliably honors HELLO's gameId=GameIds.nexus - a realm/dungeon
    # server just re-serves its own instance instead (confirmed live: see
    # gameScreen._directNexus). Used to make NEXUS_MODE_DIRECT_CONNECT
    # actually land in the Nexus instead of wherever CURR_SERVER points now.
    HOME_SERVER: str
    TICKER : Ticker
    LISTENER : Listener
    SENDER : Sender
    INCOMINGQUEUE : queue.Queue
    OUTGOINGQUEUE : queue.Queue
    DEBUGGER : Debugger
    RNG : random.Random
    TILE_CHAR_CACHE : Dict[Tuple[str, int, int, int], str]
    # buildVisibleTiles's reusable scratch buffers (Models/TileManager.py) -
    # cleared and refilled each frame instead of reallocated.
    PER_TILE_INDEX : PerTileIndex
    VISIBLE_TILES_BUFFER : Dict[Tuple[int, int], RenderCell]
    # None means nothing selected/peeked yet.
    SELECTED_SLOT : SelectedSlot | None
    PEEKED_OBJECT_TYPE : int | None
    # Cycle index into the bottom panel's current bag/portal candidates - reset when the candidate set changes.
    BOTTOM_PANEL_CYCLE_INDEX : int
    BOTTOM_PANEL_CANDIDATE_IDS : FrozenSet[int]
    CURR_MAP_NAME : str
    # Popped by _establishConnection to build the follow-up HELLO after a RECONNECT.
    PENDING_RECONNECT_HELLO : PendingReconnectHello
    BACKGROUND_TEXTURE_CACHE : List[Tuple[int, int, str, int]]
    BACKGROUND_TEXTURE_DIMS : Tuple[int, int]
    BACKGROUND_TEXTURE_LAST_REGEN : float
    # Chat panel state - see Renders/GameScreen/chatPanel.py.
    CHAT_MESSAGES : Deque[ChatMessage]
    CHAT_INPUT : str
    CHAT_TYPING : bool
    # Player-configurable keybinds - loaded once at app start (see
    # Utils/json/keybindLoader.py), consumed via Renders/GameScreen/inputRouter.py.
    KEYBINDS : Dict[str, str]


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
