import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from deploy.receive import extract_bundle


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
