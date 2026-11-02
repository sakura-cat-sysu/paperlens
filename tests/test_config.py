import config
from config import Settings, load_settings


def test_settings_hide_key_in_repr():
    assert "private-token" not in repr(Settings(api_key="private-token", model="test-model"))


def test_env_file_reload_and_process_environment_precedence(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=local-test\nOPENAI_MODEL=first\n", encoding="utf-8")
    assert load_settings().model == "first"
    path.write_text("OPENAI_API_KEY=local-test\nOPENAI_MODEL=second\n", encoding="utf-8")
    assert load_settings().model == "second"
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    assert load_settings().model == "environment-model"
    assert load_settings().base_url == ""
