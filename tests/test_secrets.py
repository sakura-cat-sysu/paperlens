"""密钥加密与模型配置解析的单元测试。

不连数据库：配置用内存 SQLite，主密钥写到临时目录。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from config import Settings


@pytest.fixture
def secret_file(tmp_path, monkeypatch):
    from backend import secrets

    monkeypatch.setenv("PAPERLENS_SECRET_KEY", "")
    monkeypatch.setattr(secrets, "KEY_FILE", tmp_path / "secret.key")
    secrets.reset_cache()
    yield tmp_path / "secret.key"
    secrets.reset_cache()


@pytest.fixture
def session(secret_file):
    from backend.database import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def test_encrypt_roundtrip_never_stores_plaintext(secret_file):
    from backend import secrets

    value = "sk-abcdef1234567890"
    cipher = secrets.encrypt(value)
    assert cipher
    assert value not in cipher
    assert secrets.decrypt(cipher) == value
    assert secret_file.exists()


def test_empty_value_stays_empty(secret_file):
    from backend import secrets

    assert secrets.encrypt("") == ""
    assert secrets.decrypt("") == ""


def test_hint_only_reveals_edges(secret_file):
    from backend import secrets

    masked = secrets.hint("sk-abcdef1234567890")
    assert masked == "sk-…7890"
    assert "abcdef" not in masked
    assert secrets.hint("short") == "…rt"


def test_corrupted_cipher_raises_secret_error(secret_file):
    from backend import secrets

    with pytest.raises(secrets.SecretError):
        secrets.decrypt("this-is-not-a-valid-token")


def test_different_master_key_cannot_decrypt(secret_file, tmp_path, monkeypatch):
    from backend import secrets

    cipher = secrets.encrypt("sk-original-0001")
    # 换一个主密钥文件后，旧密文应当无法解开，而不是静默返回错误内容。
    monkeypatch.setattr(secrets, "KEY_FILE", tmp_path / "other.key")
    secrets.reset_cache()
    with pytest.raises(secrets.SecretError):
        secrets.decrypt(cipher)


@pytest.fixture
def account(session, monkeypatch):
    from backend import account as module

    monkeypatch.setattr(
        module,
        "load_settings",
        lambda: Settings(
            api_key="sk-env-0000", model="env-model", base_url="https://env.example"
        ),
    )
    return module


def add_config(
    session,
    owner,
    name,
    key="sk-test-0001",
    *,
    model="model-1",
    base_url="https://api.example",
    protocol="chat",
):
    """owner=None 表示全局配置。"""
    from backend.database import ModelConfig
    from backend.secrets import encrypt, hint

    row = ModelConfig(
        owner_id=owner,
        name=name,
        api_key_cipher=encrypt(key) if key else "",
        api_key_hint=hint(key) if key else "",
        base_url=base_url,
        model=model,
        protocol=protocol,
    )
    session.add(row)
    session.commit()
    return row


def test_environment_is_used_when_nothing_saved(account, session):
    settings = account.settings_for(session, "user-1")
    assert settings.api_key == "sk-env-0000"
    assert settings.model == "env-model"


def test_global_config_is_shared_by_everyone(account, session):
    add_config(session, None, "全局配置", "sk-global-2222", model="global-model")
    for user_id in ("user-1", "user-2"):
        settings = account.settings_for(session, user_id)
        assert settings.api_key == "sk-global-2222"
        assert settings.model == "global-model"


def test_any_personal_config_beats_global(account, session):
    add_config(session, None, "全局配置", "sk-global-2222")
    add_config(session, "user-1", "我的配置", "sk-user-1111")
    assert account.settings_for(session, "user-1").api_key == "sk-user-1111"
    # 别的账号不受影响。
    assert account.settings_for(session, "user-2").api_key == "sk-global-2222"


def test_default_uses_the_newest_personal_config(account, session):
    add_config(session, "user-1", "配置 A", "sk-a-0001")
    add_config(session, "user-1", "配置 B", "sk-b-0002")
    assert account.settings_for(session, "user-1").api_key == "sk-b-0002"


def test_explicit_choice_wins_over_default(account, session):
    first = add_config(session, "user-1", "配置 A", "sk-a-0001")
    add_config(session, "user-1", "配置 B", "sk-b-0002")
    assert account.settings_for(session, "user-1", first.id).api_key == "sk-a-0001"


def test_cannot_select_someone_elses_config(account, session):
    other = add_config(session, "user-2", "别人的", "sk-other-0001")
    with pytest.raises(account.ConfigNotFound):
        account.settings_for(session, "user-1", other.id)


def test_unknown_config_is_rejected(account, session):
    with pytest.raises(account.ConfigNotFound):
        account.settings_for(session, "user-1", "missing-id")


def test_config_without_key_is_unusable(account, session):
    row = add_config(session, "user-1", "空配置", "")
    with pytest.raises(account.ConfigUnusable):
        account.settings_for(session, "user-1", row.id)


def test_blank_base_url_falls_back_to_environment(account, session):
    row = add_config(session, "user-1", "只有密钥", "sk-only-0001", base_url="", model="")
    settings = account.settings_for(session, "user-1", row.id)
    assert settings.base_url == "https://env.example"
    assert settings.model == "env-model"


def test_options_list_global_then_personal_then_environment(account, session):
    add_config(session, None, "全局配置", "sk-global-2222")
    add_config(session, "user-1", "我的配置", "sk-user-1111")
    add_config(session, "user-1", "空配置", "")
    views = account.options(session, "user-1")
    assert [view.scope for view in views] == ["global", "personal", "environment"]
    # 没填密钥的配置不会出现在可选列表里。
    assert all(view.configured for view in views)


def test_multiple_global_configs_are_all_selectable(account, session):
    add_config(session, None, "全局 A", "sk-a-0001")
    add_config(session, None, "全局 B", "sk-b-0002")
    names = [view.name for view in account.options(session, "user-1") if view.scope == "global"]
    assert names == ["全局 A", "全局 B"]
    # 未指定时回退到最新的一条全局配置。
    assert account.settings_for(session, "user-1").api_key == "sk-b-0002"


def test_key_is_required_when_creating_a_config(account, session):
    from fastapi import HTTPException

    from backend.schemas import ModelConfigUpdate

    with pytest.raises(HTTPException):
        account._require_key(ModelConfigUpdate(name="没有密钥"))
    # 编辑已有密钥的配置时，留空表示沿用旧密钥。
    existing = add_config(session, "user-1", "已有", "sk-existing-0001")
    account._require_key(ModelConfigUpdate(name="改名"), existing)



def test_has_any_config_reflects_availability(account, session, monkeypatch):
    assert account.has_any_config(session, "user-1") is True  # 来自 .env
    monkeypatch.setattr(
        account, "load_settings", lambda: Settings(model="m", base_url="")
    )
    assert account.has_any_config(session, "user-1") is False
    add_config(session, "user-1", "我的配置", "sk-user-1111")
    assert account.has_any_config(session, "user-1") is True


def test_protocol_follows_the_selected_config(account, session):
    chat_row = add_config(session, "user-1", "Chat", "sk-a-0001", protocol="chat")
    anthropic_row = add_config(
        session, "user-1", "Claude", "sk-ant-0002", protocol="messages"
    )
    assert account.settings_for(session, "user-1", chat_row.id).protocol == "chat"
    assert (
        account.settings_for(session, "user-1", anthropic_row.id).protocol
        == "messages"
    )
    # 视图里也带上协议，界面才能显示。
    view = account._view(anthropic_row, "personal")
    assert view.protocol == "messages"


def test_broken_cipher_is_reported(account, session):
    from backend.secrets import SecretError

    row = add_config(session, "user-1", "坏密钥", "sk-broken-9999")
    row.api_key_cipher = "corrupted"
    session.commit()
    with pytest.raises(SecretError):
        account.settings_for(session, "user-1", row.id)


def _user(session, email="user@example.com"):
    from backend.auth import password_hash
    from backend.database import User

    user = User(email=email, password_hash=password_hash("password-123456"))
    session.add(user)
    session.commit()
    return user


def test_reserve_analysis_accepts_the_chosen_config(account, session):
    from backend.jobs import reserve_analysis

    user = _user(session)
    row = add_config(session, user.id, "可用", "sk-ok-0001")
    reserve_analysis(session, user, row.id)


def test_reserve_analysis_rejects_unknown_config(account, session):
    from fastapi import HTTPException

    from backend.jobs import reserve_analysis

    user = _user(session)
    with pytest.raises(HTTPException) as error:
        reserve_analysis(session, user, "missing-id")
    assert error.value.status_code == 404


def test_reserve_analysis_reports_missing_service(account, session, monkeypatch):
    from fastapi import HTTPException

    from backend.jobs import reserve_analysis

    user = _user(session)
    # 没有任何配置，.env 也没填密钥时应当明确提示去配置，而不是创建任务。
    monkeypatch.setattr(account, "load_settings", lambda: Settings(model="m"))
    monkeypatch.setattr(
        "backend.jobs.settings",
        lambda: type("S", (), {"max_active_jobs": 2, "daily_analyses": 20})(),
    )
    with pytest.raises(HTTPException) as error:
        reserve_analysis(session, user, None)
    assert error.value.status_code == 503

