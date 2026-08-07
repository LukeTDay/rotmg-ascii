from typing import Dict
import requests
import xml.etree.ElementTree as et

def parseServersXML(r : requests.models.Response):
    xmlText = r.text
    root = et.fromstring(xmlText)
    serversDict : Dict[str,str] = {}
    for server in root.findall("Server"):
        name  = server.find("Name").text
        dns   = server.find("DNS").text
        if name is None:
            continue
        if dns is None:
            continue
        serversDict[name] = dns
    return serversDict
    



