from typing import Dict
import requests
import xml.etree.ElementTree as et

def parseServersXML(r : requests.models.Response):
    xmlText = r.text
    root = et.fromstring(xmlText)
    serversDict : Dict[str,str] = {}
    for server in root.findall("Server"):
        nameElem = server.find("Name")
        dnsElem  = server.find("DNS")
        if nameElem is None or dnsElem is None:
            continue
        name = nameElem.text
        dns  = dnsElem.text
        if name is None or dns is None:
            continue
        serversDict[name] = dns
    return serversDict
    



