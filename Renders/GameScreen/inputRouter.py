import curses
from typing import Dict, List, Optional, Tuple

# Single place that resolves a frame's drained keys (movementInput.drainKeys)
# against the player's configurable keybinds (ctx["KEYBINDS"], see
# Utils/json/keybindLoader.py) - replaces the hardcoded key tables that used
# to live in movementInput.py/shootInput.py/chatPanel.py. Arrow keys always
# work regardless of config, so a bad keybind can never fully lock movement
# out; only the WASD-style letter per action is configurable.

_ARROW_BY_DIRECTION: Dict[int, Tuple[float, float]] = {
    curses.KEY_UP: (0.0, -1.0),
    curses.KEY_DOWN: (0.0, 1.0),
    curses.KEY_LEFT: (-1.0, 0.0),
    curses.KEY_RIGHT: (1.0, 0.0),
}

_DIRECTION_ACTIONS: Tuple[Tuple[str, Tuple[float, float]], ...] = (
    ("moveUp", (0.0, -1.0)),
    ("moveDown", (0.0, 1.0)),
    ("moveLeft", (-1.0, 0.0)),
    ("moveRight", (1.0, 0.0)),
)

# Windows VK_UP/VK_DOWN/VK_LEFT/VK_RIGHT - paired with each direction's
# configurable letter in resolveVkByDirection below.
_ARROW_VK_BY_DIRECTION: Dict[str, int] = {
    "moveUp": 0x26,
    "moveDown": 0x28,
    "moveLeft": 0x25,
    "moveRight": 0x27,
}


def _matchesLetter(keys: List[int], letter: str) -> bool:
    if not letter:
        return False
    ch = letter[0]
    if ch.isalpha():
        return ord(ch.lower()) in keys or ord(ch.upper()) in keys
    return ord(ch) in keys


def resolveDirection(keys: List[int], keybinds: Dict[str, str]) -> Optional[Tuple[float, float]]:
    """Same "last matching key in the frame wins" behavior as the old
    hardcoded _DIRECTIONS dict - arrows are always active, the configured
    letter per direction is layered on top."""
    matches: Dict[int, Tuple[float, float]] = dict(_ARROW_BY_DIRECTION)
    for action, vector in _DIRECTION_ACTIONS:
        letter = keybinds.get(action, "")
        if not letter:
            continue
        ch = letter[0]
        if ch.isalpha():
            matches[ord(ch.lower())] = vector
            matches[ord(ch.upper())] = vector
        else:
            matches[ord(ch)] = vector

    direction: Optional[Tuple[float, float]] = None
    for key in keys:
        if key in matches:
            direction = matches[key]
    return direction


def resolveVkByDirection(keybinds: Dict[str, str]) -> Tuple[Tuple[Tuple[float, float], Tuple[int, ...]], ...]:
    """Rebuilds the Windows GetAsyncKeyState VK table fresh from ctx["KEYBINDS"]
    on every call (cheap - 4 entries) so a keybind changed via the pause menu
    takes effect immediately, no caching/reload needed. VK codes for letter
    keys equal their uppercase ASCII codes."""
    table = []
    for action, vector in _DIRECTION_ACTIONS:
        arrowVk = _ARROW_VK_BY_DIRECTION[action]
        letter = keybinds.get(action, "")
        vks = (arrowVk,) if not letter else (arrowVk, ord(letter[0].upper()))
        table.append((vector, vks))
    return tuple(table)


def isAutoFireToggle(keys: List[int], keybinds: Dict[str, str]) -> bool:
    return _matchesLetter(keys, keybinds.get("autoFire", "f"))


def isChatOpenKey(keys: List[int], keybinds: Dict[str, str]) -> bool:
    return _matchesLetter(keys, keybinds.get("openChat", "/"))


def isNexusKey(keys: List[int], keybinds: Dict[str, str]) -> bool:
    return _matchesLetter(keys, keybinds.get("nexus", "r"))


# How the nexus key behaves - see gameScreen._directNexus/ESCAPE handling.
# ESCAPE asks the server to do it and waits for its RECONNECT reply;
# DIRECT_CONNECT tears the connection down client-side immediately and
# reconnects fresh, same as the very first connect after server select -
# faster in a pinch, at the cost of trusting the client's own state instead
# of the server's.
NEXUS_MODE_FIELD = "nexusMode"
NEXUS_MODE_ESCAPE = "escape"
NEXUS_MODE_DIRECT_CONNECT = "directConnect"
_NEXUS_MODES = (NEXUS_MODE_ESCAPE, NEXUS_MODE_DIRECT_CONNECT)


def getNexusMode(keybinds: Dict[str, str]) -> str:
    mode = keybinds.get(NEXUS_MODE_FIELD, NEXUS_MODE_DIRECT_CONNECT)
    return mode if mode in _NEXUS_MODES else NEXUS_MODE_DIRECT_CONNECT


def toggleNexusMode(keybinds: Dict[str, str]) -> str:
    """Flips nexusMode to the other option and returns the new value - used
    by the keybind config screen's toggle row."""
    nextMode = NEXUS_MODE_ESCAPE if getNexusMode(keybinds) == NEXUS_MODE_DIRECT_CONNECT else NEXUS_MODE_DIRECT_CONNECT
    keybinds[NEXUS_MODE_FIELD] = nextMode
    return nextMode
