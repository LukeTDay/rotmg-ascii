from typing import Dict
import requests
import xml.etree.ElementTree as et

def parseFriendsList(r : requests.models.Response):
    xmlText = r.text
    root = et.fromstring(xmlText)

    for friend in root.findall("Account"):
        nameElement = friend.find("Name")
        nameSet = set()
        if nameElement is None:
            continue
        name = nameElement.text

        if name is None:
            continue
        nameSet.add(name)

        return nameSet