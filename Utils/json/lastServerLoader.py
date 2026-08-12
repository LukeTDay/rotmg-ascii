from typing import Optional
import json
import os
import tempfile

LAST_SERVER_DIR = "Config/Last Server/"
LAST_SERVER_PATH = LAST_SERVER_DIR + "last_server.json"


def loadLastServer() -> Optional[str]:
    """Returns the server name (matches ctx["SERVERS"] keys) picked last
    session, or None if nothing's been saved yet."""
    try:
        with open(LAST_SERVER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    return data.get("name")


def saveLastServer(name: str) -> None:
    """Atomically writes the last-selected server name, mirroring
    keybindLoader.saveKeybinds's tempfile+os.replace pattern."""
    os.makedirs(LAST_SERVER_DIR, exist_ok=True)

    tempLoc = tempfile.NamedTemporaryFile(mode="w", dir=LAST_SERVER_DIR, delete=False, encoding="utf-8")
    json.dump({"name": name}, tempLoc, indent=4)
    tempLoc.close()
    os.replace(tempLoc.name, LAST_SERVER_PATH)
