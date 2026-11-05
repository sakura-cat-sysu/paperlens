import pytest

import config
from config import Settings, load_settings


def test_settings_hide_key_in_repr():
    assert "private-token" not in repr(Settings(api_key="private-token", model="test-model"))


def test_env_file_reload_and_process_environment_precedence(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_PROTOCOL", "OPENAI_STREAM"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=local-test\nOPENAI_MODEL=first\n", encoding="utf-8")
    assert load_settings().model == "first"
    path.write_text("OPENAI_API_KEY=local-test\nOPENAI_MODEL=second\n", encoding="utf-8")
    assert load_settings().model == "second"
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    assert load_settings().model == "environment-model"
    assert load_settings().base_url == ""
    assert load_settings().protocol == "chat"
    assert load_settings().stream is False
    path.write_text("OPENAI_PROTOCOL=responses\nOPENAI_STREAM=true\n", encoding="utf-8")
    assert load_settings().protocol == "responses"
    assert load_settings().stream is True
    monkeypatch.setenv("OPENAI_PROTOCOL", "MESSAGES")
    monkeypatch.setenv("OPENAI_STREAM", "false")
    assert load_settings().protocol == "messages"
    assert load_settings().stream is False


@pytest.mark.parametrize("value", ["yes", "maybe", "private-token"])
def test_invalid_stream_setting_is_rejected_without_echoing_value(monkeypatch, tmp_path, value):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("OPENAI_STREAM", value)
    with pytest.raises(ValueError, match="OPENAI_STREAM 必须是 true 或 false") as error:
        load_settings()
    assert value not in str(error.value)
