
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

