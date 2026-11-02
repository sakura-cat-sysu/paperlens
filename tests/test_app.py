from contextlib import nullcontext
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

import config
import workflow
from config import Settings
from conftest import comparison_result, plan_result, single_result
from pdf_utils import parse_pdf

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def app(monkeypatch, settings):
    monkeypatch.setattr(config, "load_settings", lambda: settings)
    return AppTest.from_file(APP, default_timeout=15).run()


def upload_pair(at, english_pdf, chinese_pdf):
    at.file_uploader(key="uploads").set_value([
        ("en.pdf", english_pdf, "application/pdf"), ("中文.pdf", chinese_pdf, "application/pdf")
    ]).run()
    return at


def test_initial_page_and_missing_key(monkeypatch):
    at = app(monkeypatch, Settings())
    assert not at.exception
    assert at.title[0].value == "文镜 AI · PaperLens"
    assert at.button(key="analyze").disabled
    assert any("模型配置未完成" in item.value for item in at.warning)


def test_invalid_pdf_is_friendly(monkeypatch, settings):
    at = app(monkeypatch, settings)
    at.file_uploader(key="uploads").set_value([("broken.pdf", b"fake", "application/pdf")]).run()
    assert not at.exception
    assert any("不是有效的 PDF" in item.value for item in at.error)
    assert at.button(key="analyze").disabled


def test_full_ui_and_regular_interactions_do_not_repeat_api(monkeypatch, settings, mock_service, english_pdf, chinese_pdf):
    documents = (parse_pdf(english_pdf, "en.pdf", "D1"), parse_pdf(chinese_pdf, "中文.pdf", "D2"))
    service, calls = mock_service([plan_result()] + [single_result(d.pages[0].text) for d in documents] + [comparison_result()])
    monkeypatch.setattr(workflow, "LLMService", lambda cfg: nullcontext(service))
    at = app(monkeypatch, settings)
    upload_pair(at, english_pdf, chinese_pdf)
    assert at.button(key="analyze").disabled
    at.text_area(key="question").set_value("生成式 AI 是否提高学习效率？").run()
    assert not at.button(key="analyze").disabled
    at.button(key="analyze").click().run()
    assert not at.exception
    assert at.session_state["report"] is not None
    assert not at.session_state["busy"]
    assert len(calls) == 4
    assert at.button(key="analyze").disabled
    assert {s.value for s in at.subheader} >= {"综合结论", "文献观点", "共识与分歧", "证据来源", "尚待研究的问题"}
    at.selectbox(key="page_D1").select(2).run()
    at.run()
    assert at.session_state["report"] is not None
    assert len(calls) == 4
    at.text_area(key="question").set_value("新的研究问题").run()
    assert at.session_state["report"] is None
    assert at.session_state["stage_cache"] == {}
    assert len(calls) == 4


def test_ui_timeout_can_retry_without_repeating_finished_documents(monkeypatch, settings, mock_service, english_pdf, chinese_pdf):
    d1 = parse_pdf(english_pdf, "en.pdf", "D1")
    d2 = parse_pdf(chinese_pdf, "中文.pdf", "D2")
    service, calls = mock_service([plan_result(), single_result(d1.pages[0].text), httpx.ReadTimeout("timeout"),
                                   single_result(d2.pages[0].text), comparison_result()])
    monkeypatch.setattr(workflow, "LLMService", lambda cfg: nullcontext(service))
    at = upload_pair(app(monkeypatch, settings), english_pdf, chinese_pdf)
    at.text_area(key="question").set_value("研究问题").run()
    at.button(key="analyze").click().run()
    assert not at.exception
    assert any("超时" in e.value for e in at.error)
    assert not at.button(key="analyze").disabled
    assert not at.session_state["busy"]
    at.button(key="analyze").click().run()
    assert not at.exception
    assert at.session_state["report"] is not None
    assert len(calls) == 5


def test_upload_change_hides_old_report(monkeypatch, settings, mock_service, english_pdf, chinese_pdf):
    docs = (parse_pdf(english_pdf, "en.pdf", "D1"), parse_pdf(chinese_pdf, "中文.pdf", "D2"))
    service, calls = mock_service([plan_result()] + [single_result(d.pages[0].text) for d in docs] + [comparison_result()])
    monkeypatch.setattr(workflow, "LLMService", lambda cfg: nullcontext(service))
    at = upload_pair(app(monkeypatch, settings), english_pdf, chinese_pdf)
    at.text_area(key="question").set_value("问题").run()
    at.button(key="analyze").click().run()
    assert at.session_state["report"]
    at.file_uploader(key="uploads").clear().run()
    assert not at.exception
    assert at.session_state["report"] is None
    assert at.button(key="analyze").disabled
    assert len(calls) == 4
