from typing import Tuple, Dict
from Constants import ApiPoints
from hashlib import md5

import requests
import re

def getAccessAndClientToken(accountDict : Dict[str,str]) -> Tuple[bool,Tuple[str,str]]:
    alias     : str = accountDict["alias"]
    email     : str = accountDict["email"]
    password  : str = accountDict["password"]
    clientToken : str = md5((email.encode("utf-8") + password.encode("utf-8"))).hexdigest()
    r = requests.post(ApiPoints.VERIFY, data={"guid": email,
                                                "password": password,
                                                "clientToken": clientToken,
                                                "game_net": "Unity", "play_platform": "Unity", "game_net_user_id": ""}, headers=ApiPoints.launcherHeaders)
    pattern = r"AccessToken>(.+)</AccessToken>"

    try:
        accessToken = re.findall(pattern, r.text)[0]
    except IndexError as e:
        return(False, f"{e}")
    print(accessToken)

    r = requests.post(ApiPoints.VERIFYTOKEN, data={"clientToken": clientToken,
                                                           "accessToken": accessToken,
                                                           "game_net": "Unity", "play_platform": "Unity", "game_net_user_id": ""}, headers=ApiPoints.launcherHeaders)

    if not "Success" in r.text:
        return (False, f"Error when verfiying token {r.text}")

    return (True, (accessToken,clientToken))