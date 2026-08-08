from typing import TypedDict, List, Dict, Set, TypeVar

from Models.CharListData import CharListData


class AccountData(TypedDict):
    alias: str
    email: str
    password: str


class Context(TypedDict, total=False):
    account: AccountData
    accessToken: str
    clientToken: str
    CHARLIST: List[CharListData]
    FRIENDSLIST: Set[str]
    GUILDMEMBERS: Set[str]
    SERVERS: Dict[str, str]
    CURR_CHAR_ID: int


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
