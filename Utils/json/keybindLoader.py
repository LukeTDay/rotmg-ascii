from typing import Dict
import json
import os
import tempfile

DEFAULT_KEYBINDS_PATH = "Resources/keybindsDefault.json"
PERSONAL_KEYBINDS_PATH = "Credentials/keybinds.json"


def loadKeybinds() -> Dict[str, str]:
    """Loads the shipped default keybinds, then overlays the player's personal
    Credentials/keybinds.json on top (field by field) if it exists. Field
    order follows the default file, giving the config editor a stable
    display order."""
    with open(DEFAULT_KEYBINDS_PATH, "r", encoding="utf-8") as f:
        keybinds: Dict[str, str] = json.load(f)

    try:
        with open(PERSONAL_KEYBINDS_PATH, "r", encoding="utf-8") as f:
            overrides: Dict[str, str] = json.load(f)
    except FileNotFoundError:
        return keybinds

    keybinds.update(overrides)
    return keybinds


def saveKeybinds(keybinds: Dict[str, str]) -> None:
    """Atomically writes the player's personal keybind overrides, mirroring
    accountSelect.py/enterAccountInfo.py's tempfile+os.replace pattern for
    Credentials/account_credentials.json."""
    if not os.path.isdir("Credentials/"):
        os.mkdir("Credentials")

    tempLoc = tempfile.NamedTemporaryFile(mode="w", dir="Credentials/", delete=False, encoding="utf-8")
    json.dump(keybinds, tempLoc, indent=4)
    tempLoc.close()
    os.replace(tempLoc.name, PERSONAL_KEYBINDS_PATH)
