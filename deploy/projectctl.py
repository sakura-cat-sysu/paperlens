#!/usr/bin/python3
"""仅允许对 PaperLens 当前 release 执行预定义运维命令。"""

import os
from pathlib import Path
import pwd
import subprocess
import sys

ROOT = Path("/opt/paperlens")


def main():
    verbs = {"status", "logs", "restart", "backup"}
    if len(sys.argv) != 2 or sys.argv[1] not in verbs:
        raise SystemExit("Usage: paperlensctl {status|logs|restart|backup}")
    account = pwd.getpwnam("paperlens")
    if os.geteuid() != account.pw_uid:
        os.execv(
            "/usr/bin/sudo",
            ["sudo", "-n", "-u", "paperlens", "--", "/usr/local/bin/paperlensctl", sys.argv[1]],
        )
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": account.pw_dir,
        "USER": "paperlens",
        "XDG_RUNTIME_DIR": f"/run/user/{account.pw_uid}",
        "DOCKER_HOST": f"unix:///run/user/{account.pw_uid}/docker.sock",
        "PAPERLENS_ROOT": str(ROOT),
    }
    release = (ROOT / "current").resolve()
    if not (release / "images.env").is_file():
        raise SystemExit("PaperLens has no deployed release yet")
    if sys.argv[1] == "backup":
        result = subprocess.run(["bash", str(release / "deploy/backup.sh")], env=env)
    else:
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(ROOT / ".env"),
            "--env-file",
            str(release / "images.env"),
            "-f",
            str(release / "compose.yaml"),
            "-f",
            str(release / "compose.shared.yaml"),
        ]
        actions = {
            "status": ["ps"],
            "logs": ["logs", "--tail", "100", "api", "worker", "scheduler"],
            "restart": ["restart", "api", "worker", "scheduler", "web"],
        }
        result = subprocess.run([*command, *actions[sys.argv[1]]], env={**env, "RELEASE_DIR": str(release)})
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
