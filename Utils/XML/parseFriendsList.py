import requests
import xml.etree.ElementTree as et

def parseFriendsList(r : requests.models.Response, debugger):
    xmlText = r.text
    root = et.fromstring(xmlText)
    nameSet = set()
    for friend in root.findall("Account"):
        nameElement = friend.find("Name")
        if nameElement is None:
            debugger.warning("Skipped <Account> element missing Name")
            continue
        name = nameElement.text

        if name is None:
            debugger.warning("Skipped <Account> element with empty Name")
            continue
        nameSet.add(name)

    return nameSet