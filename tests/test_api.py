"""真实 PostgreSQL + ASGI，模型使用已有 SDK Mock 传输，不产生模型费用。"""

import os
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from conftest import comparison_result, plan_result, single_result


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "mock-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    from backend.settings import settings
    from backend.database import Base, engine, session_factory

    settings.cache_clear()
    session_factory.cache_clear()
    engine.cache_clear()
    Base.metadata.create_all(engine())
    with session_factory()() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(delete(table))
        session.commit()
    from backend.worker import execute

    monkeypatch.setattr(execute, "apply_async", lambda **kwargs: None)
    from backend.app import app

    with TestClient(app) as client:
        yield client
    engine().dispose()
    engine.cache_clear()
    session_factory.cache_clear()
    settings.cache_clear()


def make_invite(*, max_uses=1, grants_admin=False, expires_in_days=14, revoked=False):
    """直接在数据库签发邀请码，返回明文。不经过管理员接口，便于引导首个账号。"""
    from datetime import timedelta

    from backend.admin import generate_code
    from backend.auth import digest
    from backend.database import InviteCode, now, session_factory

    code = generate_code()
    with session_factory()() as session:
        invite = InviteCode(
            code_hash=digest(code),
            code_hint=f"{code[:2]}****{code[-2:]}",
            grants_admin=grants_admin,
            max_uses=max_uses,
            expires_at=now() + timedelta(days=expires_in_days) if expires_in_days else None,
            revoked_at=now() if revoked else None,
        )
        session.add(invite)
        session.commit()
    return code


def register(client, email="reader@example.com", *, code=None, grants_admin=False):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "test-password-123",
            "invite_code": code or make_invite(grants_admin=grants_admin),
        },
    )
    assert response.status_code == 201, response.text
    client.headers["x-csrf-token"] = response.json()["csrf_token"]
    return response.json()["user"]


def upload_pair(client, english_pdf, chinese_pdf):
    ids = []
    for name, content in (("English.pdf", english_pdf), ("中文文献.pdf", chinese_pdf)):
        response = client.post("/api/documents", files={"file": (name, content, "application/pdf")})
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    return ids


def create(client, ids, **extra):
    payload = {
        "question": "两篇文献有哪些共同观点？",
        "document_ids": ids,
        "submission_id": str(uuid4()),
        **extra,
    }
    response = client.post("/api/analyses", json=payload)
    assert response.status_code == 202, response.text
    return response.json(), payload


def process(job_id, service):
    from backend.database import session_factory
    from backend.worker import run_job

    with session_factory()() as session:
        run_job(session, job_id, service=service)


def test_auth_csrf_origin_cookie_and_logout(api_client):
    client = api_client
    assert client.get("/api/documents").status_code == 401
    user = register(client)
    assert user["email"] == "reader@example.com"
    assert "password" not in str(user)
    assert client.get("/api/auth/me").json()["user"] == user
    assert client.post("/api/auth/logout", headers={"x-csrf-token": "wrong"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"origin": "https://other.invalid"}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    response = client.post(
        "/api/auth/login", json={"email": "READER@example.com", "password": "test-password-123"}
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    from backend.database import LoginSession, session_factory

    with session_factory()() as session:
        stored = session.scalars(select(LoginSession)).one()
        assert stored.token_hash != client.cookies.get("paperlens_session")


def test_login_rate_limit_and_validation_redaction(api_client):
    client = api_client
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/login", json={"email": "a@example.com", "password": "wrong-password-123"}
            ).status_code
            == 401
        )
    response = client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "wrong-password-123"}
    )
    assert response.status_code == 429
    response = client.post("/api/auth/login", json={"email": "invalid", "password": "secret-value"})
    assert response.status_code == 422
    assert "secret-value" not in response.text


def test_registration_can_be_closed(api_client, monkeypatch):
    from backend.settings import settings

    monkeypatch.setattr(settings(), "allow_registration", False)
    assert api_client.get("/api/capabilities").json()["allow_registration"] is False
    assert (
        api_client.post(
            "/api/auth/register",
            json={
                "email": "a@example.com",
                "password": "test-password-123",
                "invite_code": make_invite(),
            },
        ).status_code
        == 403
    )


def test_registration_requires_a_usable_invite_code(api_client):
    client = api_client
    assert client.get("/api/capabilities").json()["invite_required"] is True
    # 缺少邀请码字段被模型校验拒绝。
    assert (
        client.post(
            "/api/auth/register", json={"email": "a@example.com", "password": "test-password-123"}
        ).status_code
        == 422
    )
    for code in ("WRONGCODEWRONGCO", make_invite(revoked=True)):
        response = client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "test-password-123", "invite_code": code},
        )
        assert response.status_code == 403, response.text
    # 单次邀请码用过即失效，且注册出来的是普通用户。
    code = make_invite(max_uses=1)
    user = register(client, "first@example.com", code=code)
    assert user["is_admin"] is False
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "second@example.com", "password": "test-password-123", "invite_code": code},
        ).status_code
        == 403
    )


def test_invite_code_accepts_hyphens_and_lowercase(api_client):
    code = make_invite()
    grouped = "-".join(code[i : i + 4] for i in range(0, len(code), 4)).lower()
    user = register(api_client, "normalized@example.com", code=grouped)
    assert user["email"] == "normalized@example.com"


def test_admin_invite_endpoints_require_admin_and_track_usage(api_client):
    client = api_client
    register(client, "member@example.com")
    assert client.get("/api/admin/invites").status_code == 403
    assert client.post("/api/admin/invites", json={}).status_code == 403
    client.post("/api/auth/logout")

    admin = register(client, "boss@example.com", grants_admin=True)
    assert admin["is_admin"] is True

    issued = client.post(
        "/api/admin/invites", json={"note": "合作组", "max_uses": 2, "expires_in_days": 7}
    )
    assert issued.status_code == 201, issued.text
    body = issued.json()
    assert len(body["code"]) == 16
    # 掩码保留前两位和后两位，中间不泄露。
    assert body["code_hint"] == f"{body['code'][:2]}****{body['code'][-2:]}"
    assert body["state"] == "active" and body["used_count"] == 0

    listed = client.get("/api/admin/invites").json()
    # 列表含两个引导账号用掉的邀请码，加上刚签发的这个。
    assert len(listed) == 3
    assert listed[0]["id"] == body["id"]
    # 列表接口只返回尾号，不回传明文。
    assert "code" not in listed[0]
    assert body["code"] not in client.get("/api/admin/invites").text

    client.post("/api/auth/logout")
    register(client, "invited@example.com", code=body["code"])
    client.post("/api/auth/logout")

    register(client, "boss2@example.com", grants_admin=True)
    after = next(item for item in client.get("/api/admin/invites").json() if item["id"] == body["id"])
    assert after["used_count"] == 1 and after["state"] == "active"

    revoked = client.post(f"/api/admin/invites/{body['id']}/revoke")
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert client.post("/api/admin/invites/missing-id/revoke").status_code == 404
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "late@example.com", "password": "test-password-123", "invite_code": body["code"]},
        ).status_code
        == 403
    )


def test_admin_invite_can_grant_admin_rights(api_client):
    client = api_client
    register(client, "root@example.com", grants_admin=True)
    code = client.post("/api/admin/invites", json={"grants_admin": True}).json()["code"]
    client.post("/api/auth/logout")
    promoted = register(client, "deputy@example.com", code=code)
    assert promoted["is_admin"] is True
    assert client.get("/api/admin/invites").status_code == 200


def test_documents_parsed_deduplicated_owned_and_deleted(api_client, english_pdf, chinese_pdf):
    client = api_client
    register(client)
    ids = upload_pair(client, english_pdf, chinese_pdf)
    duplicate = client.post(
        "/api/documents", files={"file": ("duplicate.pdf", english_pdf, "application/pdf")}
    )
    assert duplicate.json()["id"] == ids[0]
    assert len(client.get("/api/documents").json()) == 2
    detail = client.get(f"/api/documents/{ids[1]}").json()
    assert detail["page_count"] == 2
    assert "生成式" in detail["pages"][0]["text"]
    assert client.get(f"/api/documents/{ids[0]}/file").content == english_pdf
    client.post("/api/auth/logout")
    register(client, "another@example.com")
    for suffix in ("", "/file"):
        assert client.get(f"/api/documents/{ids[0]}{suffix}").status_code == 404
    assert client.delete(f"/api/documents/{ids[0]}").status_code == 404
    assert (
        client.post(
            "/api/analyses", json={"question": "问题", "document_ids": ids, "submission_id": str(uuid4())}
        ).status_code
        == 404
    )


def test_invalid_pdf_limit_and_document_quota(api_client, english_pdf, chinese_pdf, monkeypatch):
    client = api_client
    register(client)
    assert (
        client.post("/api/documents", files={"file": ("bad.pdf", b"invalid", "application/pdf")}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/documents", files={"file": ("large.pdf", b"x" * (10 * 1024 * 1024 + 1))}
        ).status_code
        == 422
    )
    from backend.settings import settings

    monkeypatch.setattr(settings(), "max_documents", 1)
    assert client.post("/api/documents", files={"file": ("en.pdf", english_pdf)}).status_code == 201
    assert client.post("/api/documents", files={"file": ("zh.pdf", chinese_pdf)}).status_code == 409


def test_job_idempotency_quota_and_pending_recovery(api_client, english_pdf, chinese_pdf, monkeypatch):
    client = api_client
    register(client)
    ids = upload_pair(client, english_pdf, chinese_pdf)
    from backend.worker import dispatch, execute
    from backend.settings import settings

    monkeypatch.setattr(settings(), "daily_analyses", 1)
    calls = []

    def unavailable(**kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(execute, "apply_async", unavailable)
    job, payload = create(client, ids)
    assert job["status"] == "queued"
    duplicate = client.post("/api/analyses", json=payload)
    assert duplicate.json()["id"] == job["id"]
    assert client.get("/api/usage").json()["used"] == 1
    assert client.post("/api/analyses", json={**payload, "submission_id": str(uuid4())}).status_code == 429
    monkeypatch.setattr(execute, "apply_async", lambda **kwargs: calls.append(kwargs))
    dispatch.run()
    assert calls[0]["args"] == [job["id"]]
    assert client.delete(f"/api/documents/{ids[0]}").status_code == 409
    assert client.delete(f"/api/analyses/{job['id']}").status_code == 409


def test_complete_report_persistence_sse_no_duplicate_and_deletion(
    api_client, english_pdf, chinese_pdf, mock_service
):
    client = api_client
    register(client)
    ids = upload_pair(client, english_pdf, chinese_pdf)
    texts = [client.get(f"/api/documents/{id}").json()["pages"][0]["text"] for id in ids]
    job, _ = create(client, ids)
    service, calls = mock_service(
        [plan_result(), *[single_result(text) for text in texts], comparison_result()]
    )
    process(job["id"], service)
    detail = client.get(f"/api/analyses/{job['id']}").json()
    assert detail["status"] == "completed" and detail["coverage_complete"]
    assert len(calls) == 4
    assert detail["report"]["documents"][1]["document_id"] == "D2"
    process(job["id"], service)
    assert len(calls) == 4
    assert "completed" in client.get(f"/api/analyses/{job['id']}/events").text
    assert client.delete(f"/api/documents/{ids[0]}").status_code == 204
    assert client.get(f"/api/analyses/{job['id']}").json()["report"]["documents"][0]["pages"]
    assert client.delete(f"/api/analyses/{job['id']}").status_code == 204
    assert client.get(f"/api/analyses/{job['id']}").status_code == 404


def test_failed_stage_retry_reuses_checkpoints(api_client, english_pdf, chinese_pdf, mock_service):
    client = api_client
    register(client)
    ids = upload_pair(client, english_pdf, chinese_pdf)
    texts = [client.get(f"/api/documents/{id}").json()["pages"][0]["text"] for id in ids]
    job, _ = create(client, ids)
    service, calls = mock_service(
        [
            plan_result(),
            single_result(texts[0]),
            httpx.ReadTimeout("timeout"),
            single_result(texts[1]),
            comparison_result(),
        ]
    )
    process(job["id"], service)
    assert client.get(f"/api/analyses/{job['id']}").json()["status"] == "failed"
    assert client.post(f"/api/analyses/{job['id']}/retry").status_code == 202
    process(job["id"], service)
    assert client.get(f"/api/analyses/{job['id']}").json()["coverage_complete"]
    assert len(calls) == 5


def test_draft_retry_only_reissues_comparison_and_report_is_private(
    api_client, english_pdf, chinese_pdf, mock_service
):
    client = api_client
    register(client)
    ids = upload_pair(client, english_pdf, chinese_pdf)
    texts = [client.get(f"/api/documents/{id}").json()["pages"][0]["text"] for id in ids]
    job, _ = create(client, ids)
    draft = comparison_result()
    draft["answers"] = []
    service, calls = mock_service(
        [plan_result(), *[single_result(text) for text in texts], draft, comparison_result()]
    )
    process(job["id"], service)
    assert client.get(f"/api/analyses/{job['id']}").json()["status"] == "draft"
    assert client.post(f"/api/analyses/{job['id']}/retry").status_code == 202
    process(job["id"], service)
    assert client.get(f"/api/analyses/{job['id']}").json()["status"] == "completed"
    assert len(calls) == 5
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    for suffix in ("", "/events"):
        assert client.get(f"/api/analyses/{job['id']}{suffix}").status_code == 404
    assert client.post(f"/api/analyses/{job['id']}/retry").status_code == 404


def test_worker_advisory_lock_and_health(api_client, english_pdf, chinese_pdf):
    client = api_client
    register(client)
    ids = upload_pair(client, english_pdf, chinese_pdf)
    job, _ = create(client, ids)
    from backend.database import engine
    from backend.worker import execute
    from sqlalchemy import text
    from uuid import UUID

    key = int.from_bytes(UUID(job["id"]).bytes[:8], "big", signed=True)
    with engine().connect() as connection:
        assert connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        execute.run(job["id"])
        assert client.get(f"/api/analyses/{job['id']}").json()["status"] == "queued"
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    assert client.get("/api/health/ready").status_code == 200
    assert client.get("/api/health/live").json()["release"] == "development"
