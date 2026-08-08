import requests
import xml.etree.ElementTree as et

def parseGuildMembers(r : requests.models.Response):
    xmlText = r.text
    root = et.fromstring(xmlText)

    nameSet = set()
    for member in root.findall("Member"):
        nameElement = member.find("Name")

        if nameElement is None:
            continue

        name = nameElement.text

        if name is None:
            continue

        nameSet.add(name)

    return nameSet

