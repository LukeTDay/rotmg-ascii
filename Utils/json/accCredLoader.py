from typing import List
import json

from Models.Context import AccountData

def credential_loader() -> List[AccountData]:
    with open("Config/Account Credentials/account_credentials.json", "r", encoding="utf-8") as f:
        accounts = json.load(f)
    return accounts