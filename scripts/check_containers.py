"""验证已构建的 API / Nginx 镜像与生产 Compose；只操作独立临时测试项目。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-image", default="paperlens-api:ci")
    parser.add_argument("--web-image", default="paperlens-web:ci")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="paperlens-container-check-") as directory:
        env_file = Path(directory) / "app.env"
        env_file.write_text(
            "\n".join(
                [
                    f"API_IMAGE={args.api_image}",
                    f"WEB_IMAGE={args.web_image}",
                    f"APP_ENV_FILE={env_file}",
                    "DOMAIN=localhost",
                    "APP_ORIGIN=http://127.0.0.1:8088",
                    "POSTGRES_PASSWORD=container-check-only",
                    "RABBITMQ_PASSWORD=container-check-only",
                    "STORAGE_BACKEND=local",
                    "STORAGE_ROOT=/data/documents",
                    "DATABASE_URL=postgresql+psycopg://paperlens:container-check-only@postgres:5432/paperlens",
                    "CELERY_BROKER_URL=amqp://paperlens:container-check-only@rabbitmq:5672//",
                    "OPENAI_API_KEY=",
                    "OPENAI_MODEL=",
                ]
            )
            + "\n"
        )
        os.chmod(env_file, 0o600)
        command = [
            "docker",
            "compose",
            "--progress",
            "quiet",
            "--project-name",
            "paperlens-check-" + uuid4().hex[:10],
            "--env-file",
            str(env_file),
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(ROOT / "compose.smoke.yaml"),
        ]

        def compose(*arguments, **kwargs):
            return subprocess.run([*command, *arguments], cwd=ROOT, check=True, timeout=180, **kwargs)

        try:
            compose("up", "-d", "--wait", "postgres", "rabbitmq")
            compose("run", "--rm", "migrate")
            compose("up", "-d", "--wait", "--wait-timeout", "120", "api", "worker", "scheduler", "web")
            with urlopen("http://127.0.0.1:8088/api/health/ready", timeout=10) as response:
                assert json.load(response)["status"] == "ready"
            with urlopen("http://127.0.0.1:8088/new", timeout=10) as response:
                assert b'<div id="root">' in response.read()
                assert "default-src 'self'" in response.headers["Content-Security-Policy"]
            compose("exec", "-T", "web", "nginx", "-t")
            print("Container checks passed")
        except BaseException:
            subprocess.run([*command, "logs", "--tail", "30"], cwd=ROOT, timeout=30)
            raise
        finally:
            # 唯一随机项目内只有本脚本创建的合成数据库和临时卷。
            subprocess.run(
                [*command, "down", "--volumes", "--remove-orphans"], cwd=ROOT, check=True, timeout=90
            )


if __name__ == "__main__":
    main()
