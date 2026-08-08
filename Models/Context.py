from typing import TypedDict, List, Dict, Set

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
