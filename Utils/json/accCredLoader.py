from typing import Dict, List
import json

def credential_loader() -> List[Dict[str,str]]:
    with open("Credentials/account_credentials.json", "r", encoding="utf-8") as f:
        accounts = json.load(f)

    return accounts