import requests
import xml.etree.ElementTree as et

def parseFriendsList(r : requests.models.Response):
    xmlText = r.text
    root = et.fromstring(xmlText)
    nameSet = set()
    for friend in root.findall("Account"):
        nameElement = friend.find("Name")
        if nameElement is None:
            continue
        name = nameElement.text

        if name is None:
            continue
        nameSet.add(name)

    return nameSet