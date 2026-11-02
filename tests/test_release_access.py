import io
import importlib.util
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import pytest

from deploy.receive import extract_bundle

AUTH_MODULE = Path(__file__).resolve().parents[1] / "deploy/registry-auth.py"
spec = importlib.util.spec_from_file_location("registry_auth", AUTH_MODULE)
registry_auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry_auth)


def bundle(extra=None):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for name in (
            "compose.yaml",
            "compose.shared.yaml",
            "images.env",
            "deploy/deploy.sh",
            "deploy/compose.sh",
        ):
            entry = tarfile.TarInfo("./" + name)
            entry.size = 4
            archive.addfile(entry, io.BytesIO(b"test"))
        if extra:
            archive.addfile(extra, io.BytesIO(b"x") if extra.size else None)
    return result.getvalue()


def test_release_bundle_accepts_only_project_files(tmp_path):
    extract_bundle(bundle(), tmp_path)
    assert (tmp_path / "deploy/deploy.sh").read_bytes() == b"test"


@pytest.mark.parametrize("kind", ["traversal", "absolute", "symlink", "outside"])
def test_release_bundle_rejects_unsafe_paths(tmp_path, kind):
    names = {
        "traversal": "../outside",
        "absolute": "/tmp/outside",
        "symlink": "deploy/link",
        "outside": "other/file",
    }
    member = tarfile.TarInfo(names[kind])
    if kind == "symlink":
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
    else:
        member.size = 1
    with pytest.raises(ValueError):
        extract_bundle(bundle(member), tmp_path)


def test_registry_tokens_only_allow_paperlens_repositories():
    payload = {
        "exp": time.time() + 7200,
        "access": [
            {"type": "repository", "name": name, "actions": ["pull", "push"]}
            for name in registry_auth.REPOSITORIES
        ],
    }
    registry_auth.validate_scope(payload)
    payload["access"].append({"type": "repository", "name": "ntgmc/other-project"})
    with pytest.raises(ValueError, match="unexpected repository"):
        registry_auth.validate_scope(payload)


@pytest.mark.parametrize("remaining", [-1, 90000])
def test_registry_tokens_must_expire_soon(remaining):
    with pytest.raises(ValueError, match="short lived"):
        registry_auth.validate_scope(
            {
                "exp": time.time() + remaining,
                "access": [{"type": "repository", "name": name} for name in registry_auth.REPOSITORIES],
            }
        )


def test_ci_key_rejects_shell_commands():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "deploy/ssh-entry.py")],
        env={"SSH_ORIGINAL_COMMAND": "bash -c id"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "only accepts paperlens-deploy" in result.stderr
