#!/usr/bin/python3
"""以不可登录的服务账号接收发布包，临时 GHCR 凭据仅用于本次拉取。"""

import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path("/opt/paperlens")


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-f0-9]{40}", sys.argv[1]):
        raise SystemExit("Expected one commit SHA")
    account = pwd.getpwnam("paperlens")
    if os.geteuid() != account.pw_uid:
        raise SystemExit("Run as the paperlens service account")
    os.umask(0o077)
    credentials = json.loads(sys.stdin.buffer.readline(8192))
    if (
        not isinstance(credentials.get("username"), str)
        or not isinstance(credentials.get("token"), str)
        or not credentials["token"]
    ):
        raise SystemExit("Missing temporary registry credentials")
    payload = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
    if len(payload) > 5 * 1024 * 1024:
        raise SystemExit("Release bundle is too large")
    release = ROOT / "releases" / sys.argv[1]
    release.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix=".incoming-", dir=release.parent) as incoming,
        tempfile.TemporaryDirectory(prefix=".registry-", dir=account.pw_dir) as registry,
    ):
        staged = Path(incoming)
        extract_bundle(payload, staged)
        values = dict(line.split("=", 1) for line in (staged / "images.env").read_text().splitlines() if line)
        if values.get("RELEASE_SHA") != sys.argv[1]:
            raise SystemExit("Bundle SHA differs from requested release")
        for key, suffix in (("API_IMAGE", "api"), ("WEB_IMAGE", "web")):
            if not re.fullmatch(
                rf"ghcr\.io/sakura-cat-sysu/paperlens-{suffix}@sha256:[a-f0-9]{{64}}", values.get(key, "")
            ):
                raise SystemExit("Unexpected image repository or digest")
        if release.exists():
            # 同一 SHA 重跑时沿用已落盘的不可变镜像与脚本。
            if not (release / "images.env").is_file():
                raise SystemExit("Existing release is incomplete")
        else:
            staged.rename(release)
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": account.pw_dir,
            "USER": "paperlens",
            "XDG_RUNTIME_DIR": f"/run/user/{account.pw_uid}",
            "DOCKER_HOST": f"unix:///run/user/{account.pw_uid}/docker.sock",
            "DOCKER_CONFIG": registry,
            "PAPERLENS_ROOT": str(ROOT),
        }
        subprocess.run(
            ["docker", "login", "ghcr.io", "--username", credentials["username"], "--password-stdin"],
            input=credentials["token"],
            text=True,
            env=env,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        credentials.clear()
        subprocess.run(["bash", str(release / "deploy/deploy.sh"), str(release)], env=env, check=True)


def extract_bundle(payload: bytes, target: Path):
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe release entry")
            if path.parts and path.parts[0] not in {
                "compose.yaml",
                "compose.shared.yaml",
                "images.env",
                "deploy",
            }:
                raise ValueError("Unexpected release entry")
            total += member.size
            if total > 2 * 1024 * 1024:
                raise ValueError("Expanded release bundle is too large")
            archive.extract(member, target, filter="data")
    for name in (
        "compose.yaml",
        "compose.shared.yaml",
        "images.env",
        "deploy/deploy.sh",
        "deploy/compose.sh",
    ):
        if not (target / name).is_file():
            raise ValueError(f"Missing release file: {name}")


if __name__ == "__main__":
    main()
