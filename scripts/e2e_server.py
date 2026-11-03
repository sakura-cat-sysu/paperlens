"""仅供 Playwright：真实 API、PostgreSQL、RabbitMQ 和 Worker，模型由本机合成响应替代。"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


E2E_INVITE_CODE = "E2EBROWSERTESTAB"


def seed_invite():
    """注册需要邀请码，这里预置一个仅供浏览器测试使用的固定邀请码。"""
    from sqlalchemy import select

    from backend.auth import digest
    from backend.database import InviteCode, session_factory

    code_hash = digest(E2E_INVITE_CODE)
    with session_factory()() as session:
        invite = session.scalar(select(InviteCode).where(InviteCode.code_hash == code_hash))
        if invite is None:
            session.add(
                InviteCode(
                    code_hash=code_hash,
                    code_hint=f"{E2E_INVITE_CODE[:2]}****{E2E_INVITE_CODE[-2:]}",
                    note="browser test",
                    max_uses=100,
                )
            )
        else:
            invite.used_count = 0
            invite.revoked_at = None
        session.commit()


def main():
    database = os.environ.get("TEST_DATABASE_URL")
    if not database:
        raise SystemExit("TEST_DATABASE_URL must point to an isolated test database")
    os.environ.update(
        DATABASE_URL=database,
        APP_ORIGIN="http://127.0.0.1:5188",
        ALLOW_REGISTRATION="true",
        OPENAI_API_KEY="e2e-not-a-real-key",
        OPENAI_MODEL="synthetic-e2e",
        STORAGE_BACKEND="local",
        STORAGE_ROOT=str(Path(".cache/e2e/documents").resolve()),
    )

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            payload = json.loads(request["messages"][1]["content"])
            if "pages" in payload:
                result = {
                    "claims": [
                        {
                            "claim": "合成测试文献报告任务效率改善。",
                            "explanation": "仅用于验证产品流程。",
                            "evidence": [{"page": 1, "quote": payload["pages"][0]["text"].strip()}],
                        }
                    ],
                    "gaps": ["长期效果未测量。"],
                }
            elif "documents" in payload:
                ids = [claim["claim_id"] for document in payload["documents"] for claim in document["claims"]]
                finding = {
                    "text": "合成测试结果：两篇文献均报告任务效率改善，长期效果未测量。",
                    "claim_ids": ids,
                    "basis": "reported",
                }
                result = {
                    "summary": finding,
                    "answers": [
                        {
                            "task_id": task["task_id"],
                            "status": "answered",
                            "statements": [finding],
                            "missing_requirements": [],
                            "caveats": "人工合成测试，不是真实科研结论。",
                        }
                        for task in payload["tasks"]
                    ],
                    "agreements": [finding],
                    "disagreements": [],
                    "method_differences": [],
                    "reasons": [],
                    "unresolved_questions": ["长期效果如何？"],
                }
            else:
                result = {"tasks": [{"title": "比较文献报告的效率结果", "kind": "evidence"}]}
            response = json.dumps(
                {
                    "id": "synthetic",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "synthetic-e2e",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(result, ensure_ascii=False),
                            },
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):
            pass

    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{model.server_port}/v1"
    threading.Thread(target=model.serve_forever, daemon=True).start()
    import pymupdf

    fixtures = Path(".cache/e2e")
    fixtures.mkdir(parents=True, exist_ok=True)
    for index in (1, 2):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text(
                (50, 70),
                f"Synthetic study {index}: AI improved task completion time. Long-term retention was not measured.",
            )
            pdf.save(fixtures / f"paper-{index}.pdf")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    seed_invite()
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "backend.worker:celery",
            "worker",
            "--pool=solo",
            "--concurrency=1",
            "--loglevel=WARNING",
            f"--hostname=e2e-{os.getpid()}@%h",
        ]
    )
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"]
    )

    def stop(*args):
        for process in (api, worker):
            process.terminate()
        for process in (api, worker):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        model.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        api.wait()
    finally:
        stop()


if __name__ == "__main__":
    main()
