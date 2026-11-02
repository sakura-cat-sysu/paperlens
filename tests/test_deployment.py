"""执行真实发布脚本，替身只隔离 Docker / 公网调用，验证版本核对与回滚控制流。"""

import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("source_build", [False, True])
def test_release_promotion_or_rollback(tmp_path, failure, source_build):
    root = tmp_path / "server"
    root.mkdir()
    (root / ".env").write_text("DOMAIN=paperlens.test\n")
    releases = []
    for name in ("1" * 40, "0" * 40):
        release = root / "releases" / name
        release.mkdir(parents=True)
        (release / "compose.yaml").write_text("services: {}\n")
        (release / "images.env").write_text("RELEASE_SHA=" + "0" * 40 + "\n")
        releases.append(release)
    previous, candidate = releases
    if source_build:
        (root / "shared-host").touch()
        (candidate / "deploy").mkdir()
        (candidate / "deploy/build.sh").write_text((ROOT / "deploy/build.sh").read_text())
    (root / "current").symlink_to(previous)
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text("""#!/usr/bin/env python3
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if 'pg_dump' in sys.argv:
    print('synthetic-db-backup')
if sys.argv[1:3] == ['image', 'inspect']:
    print('sha256:' + 'a' * 64)
elif '--format' in sys.argv:
    print(json.dumps({'services': {'web': {'environment': {'DOMAIN': 'paperlens.test'}}}}))
""")
    docker.chmod(0o700)
    curl = tools / "curl"
    curl.write_text("""#!/usr/bin/env python3
import json, os
print(json.dumps({'release': os.environ['ACTUAL_SHA']}))
""")
    curl.chmod(0o700)
    log = tmp_path / "calls.jsonl"
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/deploy.sh"), str(candidate)],
        env={
            **os.environ,
            "PATH": str(tools) + ":" + os.environ["PATH"],
            "PAPERLENS_ROOT": str(root),
            "CALL_LOG": str(log),
            "ACTUAL_SHA": ("1" if failure else "0") * 40,
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert any("pg_dump" in call for call in calls)
    if source_build:
        assert len([call for call in calls if call[0] == "build"]) == 2
        assert "API_IMAGE=sha256:" in (candidate / "images.env").read_text()
        assert not any("pull" in call for call in calls)
    assert any("migrate" in call for call in calls)
    assert len(list((root / "backups").glob("*.dump"))) == 1
    if failure:
        assert result.returncode != 0
        assert (root / "current").resolve() == previous
        assert "restoring" in result.stderr
        assert any(str(previous / "compose.yaml") in call and "up" in call for call in calls)
    else:
        assert result.returncode == 0, result.stderr
        assert (root / "current").resolve() == candidate
        assert "Deployed" in result.stdout
