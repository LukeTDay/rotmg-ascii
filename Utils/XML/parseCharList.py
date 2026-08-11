from Constants.ClassIds import ALL as ALL_CLASS_IDS, CLASS_UNLOCK_REQUIREMENTS
from Models.CharData import CharData
from Models.CharListData import CharListData
import requests
import xml.etree.ElementTree as et
from typing import List

def _parseCharElement(char : et.Element, debugger) -> CharListData | None:
    charIDElement = char.get("id")
    objectTypeElement = char.find("ObjectType")
    isSeasonalElement = char.find("Seasonal")
    currentFameElement = char.find("CurrentFame")
    levelElement = char.find("Level")
    equipmentElement = char.find("Equipment")

    if (charIDElement is None or objectTypeElement is None or isSeasonalElement is None
            or currentFameElement is None or levelElement is None or equipmentElement is None):
        debugger.warning("Skipped <Char> element missing a required field")
        return None

    objectTypeText = objectTypeElement.text
    isSeasonalText = isSeasonalElement.text
    currentFameText = currentFameElement.text
    levelText = levelElement.text
    equipmentText = equipmentElement.text

    if (objectTypeText is None or isSeasonalText is None or currentFameText is None
            or levelText is None or equipmentText is None):
        debugger.warning(f"Skipped <Char id={charIDElement}> element with an empty required field")
        return None

    charID = int(charIDElement)
    objectType = int(objectTypeText)
    isSeasonal = True if isSeasonalElement.text == "True" else False
    currentFame = int(currentFameText)
    currentLevel = int(levelText)
    equipmentList = []
    for equipment in equipmentText.split(","):
        # NEWCHARACTERINFORMATION's <Equipment> suffixes ids with #uniqueData
        # (e.g. "2676#6342593521156096") - char/list's plain ids don't, so
        # this strip is a no-op there.
        equipmentList.append(int(equipment.split("#", 1)[0]))

    # Non-critical/optional: missing or empty just means "not in crucible".
    crucibleElement = char.find("CrucibleActive")
    isInCrucible = bool(crucibleElement is not None and crucibleElement.text)

    return CharListData(
        charID=charID,
        objectType=objectType,
        isSeasonal=isSeasonal,
        currentFame=currentFame,
        currentLevel=currentLevel,
        equipmentList=equipmentList,
        isInCrucible=isInCrucible
    )


def parseCharList(r : requests.models.Response, debugger):
    root = et.fromstring(r.text)
    charList = []
    for char in root.findall("Char"):
        parsed = _parseCharElement(char, debugger)
        if parsed is not None:
            charList.append(parsed)
    return charList


def parseNewCharacterXml(charXml : str, debugger) -> List[CharListData]:
    """Parses NEWCHARACTERINFORMATION's charXML: one or more bare <Char>
    elements with no <Chars> wrapper (unlike char/list) - a brand new account's
    very first character sends just one, but an account with existing
    characters sends all of them back-to-back alongside the new one. Wrapped
    in a synthetic <Chars> root so ET can parse either shape the same way."""
    root = et.fromstring(f"<Chars>{charXml}</Chars>")
    chars = []
    for char in root.findall("Char"):
        parsed = _parseCharElement(char, debugger)
        if parsed is not None:
            chars.append(parsed)
    return chars


def parseCharData(r: requests.models.Response, debugger) -> CharData:
    """Parses the same char/list response for account/class-unlock metadata
    (nextCharId/maxNumChars off the <Chars> root, per-class BestLevel off
    Account/Stats/ClassStats) rather than the per-character CharListData rows
    parseCharList returns - see Constants/ClassIds.CLASS_UNLOCK_REQUIREMENTS
    for the unlock rules applied here."""
    root = et.fromstring(r.text)
    data = CharData()

    data.charIds = [int(charId) for char in root.findall("Char")
                     if (charId := char.get("id")) is not None]

    nextCharId = root.get("nextCharId")
    maxNumChars = root.get("maxNumChars")
    if nextCharId is not None:
        data.nextCharId = int(nextCharId)
    if maxNumChars is not None:
        data.maxNumChars = int(maxNumChars)
    else:
        debugger.warning("char/list response missing maxNumChars on <Chars> root")

    accountElement = root.find("Account")
    if accountElement is not None:
        data.tutorialDone = accountElement.find("TDone") is not None
    else:
        debugger.warning("char/list response missing <Account> - defaulting tutorialDone to True")

    statsElement = root.find("Account/Stats")
    if statsElement is not None:
        for classStats in statsElement.findall("ClassStats"):
            objectTypeText = classStats.get("objectType")
            bestLevelElement = classStats.find("BestLevel")
            if objectTypeText is None or bestLevelElement is None or bestLevelElement.text is None:
                continue
            data.classBestLevels[int(objectTypeText, 16)] = int(bestLevelElement.text)

    for classId in ALL_CLASS_IDS:
        requirements = CLASS_UNLOCK_REQUIREMENTS.get(classId)
        if requirements is None:
            data.unlockedClasses.add(classId)  # e.g. Wizard - no precursor, always unlocked
            continue
        if all(data.classBestLevels.get(precursorId, 0) >= requiredLevel
               for precursorId, requiredLevel in requirements):
            data.unlockedClasses.add(classId)

    return data
