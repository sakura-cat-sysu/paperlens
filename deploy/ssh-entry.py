#!/usr/bin/python3
"""CI 公钥的 forced command；只转发受限的项目发布请求。"""

import os
import re
import sys

command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
if command == "paperlens-registry-auth":
    os.execv(sys.executable, [sys.executable, "/usr/local/libexec/paperlens-registry-auth"])
match = re.fullmatch(r"paperlens-deploy ([a-f0-9]{40})", command)
if not match:
    raise SystemExit("This key only accepts paperlens-deploy SHA or paperlens-registry-auth")
os.execv(
    "/usr/bin/sudo", ["sudo", "-n", "-u", "paperlens", "--", "/usr/local/libexec/paperlens-receive", match[1]]
)
