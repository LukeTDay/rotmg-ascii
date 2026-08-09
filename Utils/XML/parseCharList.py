from Models.CharListData import CharListData
import requests
import xml.etree.ElementTree as et

def parseCharList(r : requests.models.Response, debugger):
    xmlText = r.text
    root = et.fromstring(xmlText)

    charList = []
    for char in root.findall("Char"):
        charIDElement = char.get("id")
        objectTypeElement = char.find("ObjectType")
        isSeasonalElement = char.find("Seasonal")
        currentFameElement = char.find("CurrentFame")
        levelElement = char.find("Level")
        equipmentElement = char.find("Equipment")

        if (charIDElement is None or objectTypeElement is None or isSeasonalElement is None
                or currentFameElement is None or levelElement is None or equipmentElement is None):
            debugger.warning("Skipped <Char> element missing a required field")
            continue

        objectTypeText = objectTypeElement.text
        isSeasonalText = isSeasonalElement.text
        currentFameText = currentFameElement.text
        levelText = levelElement.text
        equipmentText = equipmentElement.text

        if (objectTypeText is None or isSeasonalText is None or currentFameText is None
                or levelText is None or equipmentText is None):
            debugger.warning(f"Skipped <Char id={charIDElement}> element with an empty required field")
            continue

        charID = int(charIDElement)
        objectType = int(objectTypeText)
        isSeasonal = True if isSeasonalElement.text == "True" else False
        currentFame = int(currentFameText)
        currentLevel = int(levelText)
        equipmentList = []
        for equipment in equipmentText.split(","):
            equipmentList.append(int(equipment))

        # Not every account/char is guaranteed to have this element, and it's
        # non-critical, so a missing/empty value just means "not in crucible"
        # rather than skipping the whole character like the fields above.
        crucibleElement = char.find("CrucibleActive")
        isInCrucible = bool(crucibleElement is not None and crucibleElement.text)

        charList.append(CharListData(
            charID=charID,
            objectType=objectType,
            isSeasonal=isSeasonal,
            currentFame=currentFame,
            currentLevel=currentLevel,
            equipmentList=equipmentList,
            isInCrucible=isInCrucible
        ))
    return charList
