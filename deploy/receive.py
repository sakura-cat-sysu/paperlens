#!/usr/bin/python3
"""服务账号接收经 CI 验证的 Git 归档，使用国内源在本机构建和发布。"""

import io
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
    os.chdir(ROOT)
    payload = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
    if len(payload) > 5 * 1024 * 1024:
        raise SystemExit("Release bundle is too large")
    release = ROOT / "releases" / sys.argv[1]
    release.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".incoming-", dir=release.parent) as incoming:
        staged = Path(incoming)
        extract_bundle(payload, staged, sys.argv[1])
        if release.exists():
            if not (release / "Dockerfile").is_file():
                raise SystemExit("Existing release is incomplete")
        else:
            staged.rename(release)
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": account.pw_dir,
            "USER": "paperlens",
            "XDG_RUNTIME_DIR": f"/run/user/{account.pw_uid}",
            "DOCKER_HOST": f"unix:///run/user/{account.pw_uid}/docker.sock",
            "PAPERLENS_ROOT": str(ROOT),
        }
        subprocess.run(["bash", str(release / "deploy/deploy.sh"), str(release)], env=env, check=True)


def extract_bundle(payload: bytes, target: Path, expected_sha: str):
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        if archive.pax_headers.get("comment") != expected_sha:
            raise ValueError("Git archive SHA differs from requested release")
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or ".git" in path.parts
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Unsafe release entry")
            total += member.size
            if total > 10 * 1024 * 1024:
                raise ValueError("Expanded release bundle is too large")
            archive.extract(member, target, filter="data")
    for name in (
        "Dockerfile",
        "frontend/Dockerfile",
        "compose.yaml",
        "compose.shared.yaml",
        "deploy/deploy.sh",
        "deploy/build.sh",
        "deploy/compose.sh",
    ):
        if not (target / name).is_file():
            raise ValueError(f"Missing release file: {name}")


if __name__ == "__main__":
    main()
