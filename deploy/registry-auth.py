#!/usr/bin/python3
"""CI 只取得 PaperLens 两个仓库的短期令牌；管理员原始凭据不离开服务器。"""

import base64
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REGISTRY = "ccr.ccs.tencentyun.com"
REPOSITORIES = {"ntgmc/paperlens-api", "ntgmc/paperlens-web"}


def main():
    config = json.loads((Path.home() / ".docker/config.json").read_text())
    auth = config["auths"][REGISTRY]["auth"]
    query = urlencode(
        [
            ("service", "token-service"),
            *(("scope", f"repository:{name}:pull,push") for name in sorted(REPOSITORIES)),
        ]
    )
    request = Request(f"https://{REGISTRY}/service/token?{query}", headers={"Authorization": "Basic " + auth})
    with urlopen(request, timeout=20) as response:
        value = json.load(response)
    token = value.get("token") or value["access_token"]
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    validate_scope(payload)
    print(json.dumps({"auths": {REGISTRY: {"registrytoken": token}}}))


def validate_scope(payload):
    scopes = payload.get("access", [])
    if {scope.get("name") for scope in scopes} != REPOSITORIES:
        raise ValueError("Registry granted unexpected repository access")
    if any(scope.get("type") != "repository" for scope in scopes):
        raise ValueError("Registry granted unexpected access type")
    if not 0 < payload.get("exp", 0) - time.time() <= 86400:
        raise ValueError("Registry token is not short lived")


if __name__ == "__main__":
    main()
