from typing import TypedDict, List, Dict, Set, Tuple, TypeVar

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
    BACKGROUND_TEXTURE_CACHE : List[Tuple[int, int, str, int]]
    BACKGROUND_TEXTURE_DIMS : Tuple[int, int]
    BACKGROUND_TEXTURE_LAST_REGEN : float


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
