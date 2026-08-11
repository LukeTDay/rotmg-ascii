
ROGUE = 768
ARCHER = 775
WIZARD = 782
PRIEST = 784
WARRIOR = 797
KNIGHT = 798
PALADIN = 799
ASSASSIN = 800
NECROMANCER = 801
HUNTRESS = 802
MYSTIC = 803
TRICKSTER = 804
SORCERER = 805
NINJA = 806
SAMURAI = 785
BARD = 796
SUMMONER = 817
KENSEI = 818
DRUID = 819

ALL = [ROGUE, ARCHER, WIZARD, PRIEST, WARRIOR, KNIGHT, PALADIN, ASSASSIN, NECROMANCER, HUNTRESS, MYSTIC, TRICKSTER, SORCERER, NINJA, SAMURAI, BARD, SUMMONER, KENSEI, DRUID]

ID_TO_CLASS = {
    ROGUE: "Rogue",
    ARCHER: "Archer",
    WIZARD: "Wizard",
    PRIEST: "Priest",
    WARRIOR: "Warrior",
    KNIGHT: "Knight",
    PALADIN: "Paladin",
    ASSASSIN: "Assassin",
    NECROMANCER: "Necromancer",
    HUNTRESS: "Huntress",
    MYSTIC: "Mystic",
    TRICKSTER: "Trickster",
    SORCERER: "Sorcerer",
    NINJA: "Ninja",
    SAMURAI: "Samurai",
    BARD: "Bard",
    SUMMONER: "Summoner",
    KENSEI: "Kensei",
    DRUID: "Druid",
}

CLASS_TO_ID = {className: classId for classId, className in ID_TO_CLASS.items()}


def idToClass(classId: int) -> str | None:
    return ID_TO_CLASS.get(classId)


def classToId(className: str) -> int | None:
    return CLASS_TO_ID.get(className)


# classId -> [(precursorClassId, requiredBestLevel), ...] - a class is unlocked once
# every precursor's <Stats>/<ClassStats>/<BestLevel> (char_list.xml, see
# Utils/XML/parseCharList.py) meets its required level. Wizard has no entry - it's
# the only unconditional root. User-supplied and confirmed 2026-08-11 against a real
# account's actual unlock state (drydessa: Rogue/Archer/Wizard/Priest/Warrior/
# Assassin/Necromancer/Huntress unlocked, all others locked).
CLASS_UNLOCK_REQUIREMENTS: dict[int, list[tuple[int, int]]] = {
    PRIEST: [(WIZARD, 5)],
    ARCHER: [(PRIEST, 5)],
    ROGUE: [(ARCHER, 5)],
    WARRIOR: [(ROGUE, 5)],

    KNIGHT: [(WARRIOR, 20)],
    PALADIN: [(PRIEST, 20), (KNIGHT, 20)],
    ASSASSIN: [(ROGUE, 20), (WIZARD, 20)],
    NECROMANCER: [(WIZARD, 20), (PRIEST, 20)],
    HUNTRESS: [(ROGUE, 20), (ARCHER, 20)],
    MYSTIC: [(NECROMANCER, 20), (HUNTRESS, 20)],
    TRICKSTER: [(PALADIN, 20), (ASSASSIN, 20)],
    SORCERER: [(ASSASSIN, 20), (NECROMANCER, 20)],
    NINJA: [(ROGUE, 20), (WARRIOR, 20)],
    SAMURAI: [(KNIGHT, 20), (NINJA, 20)],
    BARD: [(PALADIN, 20), (HUNTRESS, 20)],
    SUMMONER: [(SORCERER, 20), (MYSTIC, 20)],
    KENSEI: [(TRICKSTER, 20), (NINJA, 20)],
    DRUID: [(SORCERER, 20), (MYSTIC, 20)],
}

