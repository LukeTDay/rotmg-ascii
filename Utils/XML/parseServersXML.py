from typing import Dict
import requests
import xml.etree.ElementTree as et

def parseServersXML(r : requests.models.Response, debugger):
    xmlText = r.text
    root = et.fromstring(xmlText)
    serversDict : Dict[str,str] = {}
    for server in root.findall("Server"):
        nameElem = server.find("Name")
        dnsElem  = server.find("DNS")
        if nameElem is None or dnsElem is None:
            debugger.warning("Skipped <Server> element missing Name/DNS")
            continue
        name = nameElem.text
        dns  = dnsElem.text
        if name is None or dns is None:
            debugger.warning("Skipped <Server> element with empty Name/DNS")
            continue

        adminOnlyElem = server.find("isAdminOnly")
        if adminOnlyElem is not None and adminOnlyElem.text == "1":
            debugger.info(f"Skipped admin-only server {name!r}")
            continue

        serversDict[name] = dns
    return serversDict
    



