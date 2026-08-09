import requests
import xml.etree.ElementTree as et

def parseGuildMembers(r : requests.models.Response, debugger):
    xmlText = r.text
    root = et.fromstring(xmlText)

    nameSet = set()
    for member in root.findall("Member"):
        nameElement = member.find("Name")

        if nameElement is None:
            debugger.warning("Skipped <Member> element missing Name")
            continue

        name = nameElement.text

        if name is None:
            debugger.warning("Skipped <Member> element with empty Name")
            continue

        nameSet.add(name)

    return nameSet

