import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from deploy.receive import extract_bundle

SHA = "a" * 40


def bundle(extra=None, sha=SHA):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz", pax_headers={"comment": sha}) as archive:
        for name in (
            "Dockerfile",
            "frontend/Dockerfile",
            "compose.yaml",
            "compose.shared.yaml",
            "deploy/deploy.sh",
            "deploy/build.sh",
            "deploy/compose.sh",
        ):
            entry = tarfile.TarInfo(name)
            entry.size = 4
            archive.addfile(entry, io.BytesIO(b"test"))
        if extra:
            archive.addfile(extra, io.BytesIO(b"x") if extra.size else None)
    return result.getvalue()


def test_source_bundle_preserves_commit_identity(tmp_path):
    extract_bundle(bundle(), tmp_path, SHA)
    assert (tmp_path / "deploy/deploy.sh").read_bytes() == b"test"


def test_source_bundle_rejects_different_commit(tmp_path):
    with pytest.raises(ValueError, match="SHA differs"):
        extract_bundle(bundle(sha="b" * 40), tmp_path, SHA)


@pytest.mark.parametrize("kind", ["traversal", "absolute", "symlink", "git"])
def test_source_bundle_rejects_unsafe_paths(tmp_path, kind):
    names = {
        "traversal": "../outside",
        "absolute": "/tmp/outside",
        "symlink": "deploy/link",
        "git": ".git/config",
    }
    member = tarfile.TarInfo(names[kind])
    if kind == "symlink":
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
    else:
        member.size = 1
    with pytest.raises(ValueError):
        extract_bundle(bundle(member), tmp_path, SHA)


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
