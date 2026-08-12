from typing import Dict
import json
import os
import tempfile

DEFAULT_KEYBINDS_PATH = "Resources/keybindsDefault.json"
PERSONAL_KEYBINDS_DIR = "Config/Keybinds/"
PERSONAL_KEYBINDS_PATH = PERSONAL_KEYBINDS_DIR + "keybinds.json"


def loadKeybinds() -> Dict[str, str]:
    """Loads the shipped default keybinds, then overlays the player's personal
    Config/Keybinds/keybinds.json on top (field by field) if it exists. Field
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
    Config/Account Credentials/account_credentials.json."""
    os.makedirs(PERSONAL_KEYBINDS_DIR, exist_ok=True)

    tempLoc = tempfile.NamedTemporaryFile(mode="w", dir=PERSONAL_KEYBINDS_DIR, delete=False, encoding="utf-8")
    json.dump(keybinds, tempLoc, indent=4)
    tempLoc.close()
    os.replace(tempLoc.name, PERSONAL_KEYBINDS_PATH)
