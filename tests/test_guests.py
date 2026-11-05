"""游客使用真实数据库与会话，不访问任何真实模型。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select

from conftest import make_pdf
from test_api import api_client as api_client, create, register, upload_pair


def enter(client):
    response = client.post("/api/auth/guest")
    assert response.status_code == 200, response.text
    client.headers["x-csrf-token"] = response.json()["csrf_token"]
    return response.json()["user"]


def test_guest_entry_works_without_registration_and_uses_private_tokens(api_client, monkeypatch):
    from backend.auth import digest
    from backend.database import GuestIdentity, LoginSession, User, session_factory
    from backend.settings import settings

    monkeypatch.setattr(settings(), "allow_registration", False)
    monkeypatch.setattr(settings(), "secure_cookies", True)
    response = api_client.post("/api/auth/guest", json={"is_admin": True, "is_guest": False})
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["is_guest"] is True and user["is_admin"] is False
    for cookie in response.headers.get_list("set-cookie"):
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" in cookie
    with session_factory()() as db:
        identity = db.scalars(select(GuestIdentity)).one()
        assert identity.token_hash == digest(api_client.cookies.get("paperlens_guest"))
        session = db.scalars(select(LoginSession)).one()
        assert session.token_hash == digest(api_client.cookies.get("paperlens_session"))
        assert db.scalar(select(func.count()).select_from(User)) == 1
    assert "token_hash" not in response.text and "password_hash" not in response.text


def test_guest_entry_rejects_foreign_origin_and_keeps_csrf_checks(api_client, english_pdf):
    assert api_client.post("/api/auth/guest", headers={"origin": "https://other.invalid"}).status_code == 403
    enter(api_client)
    assert api_client.post(
        "/api/documents", files={"file": ("paper.pdf", english_pdf, "application/pdf")},
        headers={"x-csrf-token": "wrong"},
    ).status_code == 403
    assert api_client.get("/api/admin/invites").status_code == 403
    assert api_client.post("/api/admin/invites", json={}).status_code == 403


def test_guest_logout_and_reentry_reuses_identity_documents_and_quota(api_client, english_pdf, chinese_pdf):
    from backend.database import UsageDay, now, session_factory

    user = enter(api_client)
    ids = upload_pair(api_client, english_pdf, chinese_pdf)
    with session_factory()() as db:
        db.add(UsageDay(owner_id=user["id"], day=now().date(), used=4))
        db.commit()
    assert api_client.post("/api/auth/logout").status_code == 204
    assert api_client.get("/api/documents").status_code == 401
    assert api_client.cookies.get("paperlens_guest")
    assert enter(api_client)["id"] == user["id"]
    assert {d["id"] for d in api_client.get("/api/documents").json()} == set(ids)
    assert api_client.get("/api/usage").json() == {"used": 4, "limit": 10, "remaining": 6}
    # 已登录时重复进入也不会创建身份或重置次数。
    assert enter(api_client)["id"] == user["id"]
    assert api_client.get("/api/usage").json()["used"] == 4


def test_different_guests_cannot_read_files_reports_or_events(api_client, english_pdf, chinese_pdf):
    first = enter(api_client)
    ids = upload_pair(api_client, english_pdf, chinese_pdf)
    job, _ = create(api_client, ids)
    api_client.cookies.clear()
    second = enter(api_client)
    assert first["id"] != second["id"]
    assert api_client.get("/api/documents").json() == []
    assert api_client.get("/api/analyses").json() == []
    for path in (
        f"/api/documents/{ids[0]}", f"/api/documents/{ids[0]}/file",
        f"/api/analyses/{job['id']}", f"/api/analyses/{job['id']}/events",
    ):
        assert api_client.get(path).status_code == 404
    assert api_client.delete(f"/api/documents/{ids[0]}").status_code == 404
    assert api_client.post(f"/api/analyses/{job['id']}/retry").status_code == 404


def test_guest_limit_is_ten_and_duplicate_submissions_do_not_spend_twice(
    api_client, english_pdf, chinese_pdf,
):
    from backend.database import AnalysisJob, session_factory

    enter(api_client)
    ids = upload_pair(api_client, english_pdf, chinese_pdf)
    for index in range(10):
        job, payload = create(api_client, ids)
        assert api_client.post("/api/analyses", json=payload).json()["id"] == job["id"]
        assert api_client.get("/api/usage").json()["used"] == index + 1
        with session_factory()() as db:
            db.get(AnalysisJob, job["id"]).status = "completed"
            db.commit()
    response = api_client.post("/api/analyses", json={**payload, "submission_id": str(uuid4())})
    assert response.status_code == 429
    assert "08:00" in response.json()["detail"]
    assert api_client.get("/api/usage").json() == {"used": 10, "limit": 10, "remaining": 0}


def test_guest_retry_consumes_quota_and_stops_at_limit(api_client, english_pdf, chinese_pdf):
    from backend.database import AnalysisJob, UsageDay, now, session_factory

    user = enter(api_client)
    ids = upload_pair(api_client, english_pdf, chinese_pdf)
    job, _ = create(api_client, ids)
    with session_factory()() as db:
        db.get(AnalysisJob, job["id"]).status = "failed"
        db.commit()
    assert api_client.post(f"/api/analyses/{job['id']}/retry").status_code == 202
    assert api_client.get("/api/usage").json()["used"] == 2
    with session_factory()() as db:
        db.get(AnalysisJob, job["id"]).status = "failed"
        db.get(UsageDay, (user["id"], now().date())).used = 10
        db.commit()
    assert api_client.post(f"/api/analyses/{job['id']}/retry").status_code == 429
    with session_factory()() as db:
        assert db.get(AnalysisJob, job["id"]).attempts == 2


def test_guest_quota_resets_at_utc_midnight(api_client, monkeypatch):
    from backend import jobs
    from backend.database import UsageDay, session_factory

    user = enter(api_client)
    before = datetime(2026, 11, 5, 23, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(jobs, "now", lambda: before)
    with session_factory()() as db:
        db.add(UsageDay(owner_id=user["id"], day=before.date(), used=10))
        db.commit()
    assert api_client.get("/api/usage").json()["remaining"] == 0
    monkeypatch.setattr(jobs, "now", lambda: before + timedelta(minutes=2))
    assert api_client.get("/api/usage").json() == {"used": 0, "limit": 10, "remaining": 10}


def test_concurrent_guest_starts_cannot_overspend_last_allowance(api_client, english_pdf, chinese_pdf):
    from backend.database import AnalysisJob, UsageDay, now, session_factory

    user = enter(api_client)
    ids = upload_pair(api_client, english_pdf, chinese_pdf)
    with session_factory()() as db:
        db.add(UsageDay(owner_id=user["id"], day=now().date(), used=9))
        db.commit()
    def submit(_):
        return api_client.post("/api/analyses", json={
            "question": "比较研究证据。", "document_ids": ids, "submission_id": str(uuid4()),
        }).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(submit, range(2)))
    assert statuses.count(202) == 1
    assert all(s in (202, 409, 429) for s in statuses)
    assert api_client.get("/api/usage").json()["used"] == 10
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisJob)) == 1


def test_switching_to_registered_account_keeps_separate_identity_and_twenty_limit(api_client):
    guest = enter(api_client)
    regular = register(api_client)
    assert regular["is_guest"] is False
    assert enter(api_client)["id"] == regular["id"]
    assert api_client.get("/api/usage").json()["limit"] == 20
    assert api_client.post("/api/auth/logout").status_code == 204
    assert enter(api_client)["id"] == guest["id"]
    assert api_client.get("/api/usage").json()["limit"] == 10


def test_guest_creation_rate_is_atomic_and_existing_guest_can_still_resume(api_client, monkeypatch):
    from backend.settings import settings
    from backend.database import GuestEntryRate, session_factory

    monkeypatch.setattr(settings(), "guest_entries_per_window", 1)
    first = enter(api_client)
    token = api_client.cookies.get("paperlens_guest")
    api_client.cookies.clear()
    assert api_client.post("/api/auth/guest").status_code == 429
    api_client.cookies.set("paperlens_guest", token)
    assert enter(api_client)["id"] == first["id"]
    with session_factory()() as db:
        rate = db.scalars(select(GuestEntryRate)).one()
        assert rate.created == 1
        assert rate.address_hash != "testclient"


def test_expired_guest_identity_is_not_reused_and_password_login_is_disabled(api_client):
    from backend.database import GuestIdentity, now, session_factory

    first = enter(api_client)
    assert api_client.post("/api/auth/login", json={
        "email": first["email"], "password": "password-attempt-123",
    }).status_code == 401
    with session_factory()() as db:
        identity = db.scalars(select(GuestIdentity)).one()
        identity.expires_at = now() - timedelta(seconds=1)
        db.commit()
    api_client.cookies.delete("paperlens_session")
    assert enter(api_client)["id"] != first["id"]


def test_guest_mode_can_be_disabled_without_disabling_regular_accounts(api_client, monkeypatch):
    from backend.settings import settings

    enter(api_client)
    monkeypatch.setattr(settings(), "allow_guests", False)
    assert api_client.get("/api/capabilities").json()["allow_guests"] is False
    assert api_client.get("/api/documents").status_code == 403
    assert api_client.post("/api/auth/guest").status_code == 403
    api_client.post("/api/auth/logout")
    regular = register(api_client)
    assert regular["is_guest"] is False
    assert api_client.get("/api/usage").status_code == 200


def test_guest_model_unavailable_and_preview_do_not_consume_usage(api_client, monkeypatch):
    from backend import jobs
    from dataclasses import replace

    enter(api_client)
    imported = api_client.post("/api/samples/retrieval-hallucination/import")
    assert imported.status_code == 200
    ids = imported.json()["document_ids"]
    assert api_client.get(f"/api/documents/{ids[0]}").status_code == 200
    config = replace(jobs.load_settings(), api_key="")
    monkeypatch.setattr(jobs, "load_settings", lambda: config)
    response = api_client.post("/api/analyses", json={
        "document_ids": ids, "question": "比较研究结论。", "submission_id": str(uuid4()),
    })
    assert response.status_code == 503
    assert api_client.get("/api/usage").json()["used"] == 0


def test_guest_document_limit_is_enforced_for_upload_and_sample_import(api_client, monkeypatch):
    from backend.settings import settings

    monkeypatch.setattr(settings(), "guest_max_documents", 2)
    enter(api_client)
    assert api_client.post("/api/documents", files={
        "file": ("one.pdf", make_pdf(["First guest paper"]), "application/pdf"),
    }).status_code == 201
    assert api_client.post("/api/samples/long-context/import").status_code == 409
    assert len(api_client.get("/api/documents").json()) == 1
    assert api_client.post("/api/documents", files={
        "file": ("two.pdf", make_pdf(["Second guest paper"]), "application/pdf"),
    }).status_code == 201
    assert api_client.post("/api/documents", files={
        "file": ("three.pdf", make_pdf(["Third guest paper"]), "application/pdf"),
    }).status_code == 409
