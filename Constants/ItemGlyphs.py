from typing import Optional, Tuple

# Per-category inventory glyph, keyed by the weaponLabel token that names it
# (see ObjectRenderInfo.weaponLabel, a raw <Labels> string) - confirmed
# against real renderMap.json data, not guessed. Rare cosmetic/reskin
# variants map to their base type's char rather than getting their own.
_CATEGORY_CHARS = {
    # Weapons
    "SWORD": "S", "DAGGER": "D", "BOW": "B", "WAND": "W", "KATANA": "K",
    "STAFF": "Y", "MACE": "M", "SHURIKEN": "X", "SCEPTER": "C", "SHEATH": "H",
    "FLAIL": "F", "LUTE": "N",
    "TACHI": "K", "AXE": "M", "LONGBOW": "B", "DUALBLADE": "D",
    "SPELLBLADE": "D", "MORNINGSTAR": "M", "CUTLASS": "S", "DEMON_BLADE": "S",
    "CSWORD": "S", "CWAND": "W", "CBOW": "B",
    # Abilities
    "TOME": "T", "SPELL": "A", "SEAL": "E", "SKULL": "U", "ORB": "O",
    "QUIVER": "Q", "TRAP": "R", "CLOAK": "L", "SHIELD": "V", "PRISM": "P",
    "HELM": "G", "WAKIZASHI": "I",
}

# Armor split by weight class rather than one generic glyph.
_ARMOR_WEIGHT_CHARS = {"HEAVY": "[", "ROBE": "(", "LEATHER": "{"}
_ARMOR_DEFAULT_CHAR = "["  # no weight-class tag on the item - default to Heavy

RING_CHAR = "="

# Checked in this order - specific weapon/ability tokens first, armor-weight
# before the generic ARMOR fallback, ring last.
_PRIORITY_TOKENS = list(_CATEGORY_CHARS) + ["HEAVY", "ROBE", "LEATHER", "ARMOR", "RING", "AMULET"]

_HP_KEYWORDS = ("health", "life", "vitality")
_MP_KEYWORDS = ("mana", "magic", "wisdom")
POTION_COLORS = {"h": "RED", "m": "BLUE", "c": "MAGENTA"}


def resolveEquipmentChar(weaponLabel: str) -> Optional[str]:
    if not weaponLabel:
        return None
    tokens = {t.strip() for t in weaponLabel.split(",")}
    for token in _PRIORITY_TOKENS:
        if token not in tokens:
            continue
        if token in _CATEGORY_CHARS:
            return _CATEGORY_CHARS[token]
        if token in _ARMOR_WEIGHT_CHARS:
            return _ARMOR_WEIGHT_CHARS[token]
        if token == "ARMOR":
            return _ARMOR_DEFAULT_CHAR
        return RING_CHAR  # RING or AMULET
    return None


def resolvePotionChar(name: str, weaponLabel: str) -> Optional[Tuple[str, str]]:
    """Returns (char, colorName) for a health/mana/dual potion, else None -
    colorName overrides the usual tier-based color (RED/BLUE/MAGENTA)."""
    if "CONSUMABLE" not in weaponLabel:
        return None
    nameLower = name.lower()
    hasHp = any(k in nameLower for k in _HP_KEYWORDS)
    hasMp = any(k in nameLower for k in _MP_KEYWORDS)
    if hasHp and hasMp:
        return "c", POTION_COLORS["c"]
    if hasHp:
        return "h", POTION_COLORS["h"]
    if hasMp:
        return "m", POTION_COLORS["m"]
    return None
