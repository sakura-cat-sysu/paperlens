import json
from types import SimpleNamespace

import httpx
import pytest

from config import Settings
from conftest import single_result
from llm_service import AnalysisError, LLMService
from pdf_utils import parse_pdf


def test_real_sdk_mock_response(mock_service, english_pdf):
    service, calls = mock_service([single_result("AI improved task completion time in a small sample.")])
    analysis = service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "AI efficiency?")
    assert analysis.claims[0].supported
    assert len(calls) == 1
    assert calls[0]["model"] == "mock-model"
    assert "response_format" not in calls[0]
    assert "PDF 物理页码" in calls[0]["messages"][0]["content"]


def test_json_repaired_once(mock_service, english_pdf):
    service, calls = mock_service(["invalid JSON", single_result("AI improved task completion time in a small sample.")])
    assert service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "问题").claims[0].supported
    assert len(calls) == 2
    assert len(calls[1]["messages"]) == 4


def test_schema_repaired_once(mock_service, english_pdf):
    service, calls = mock_service([{"claims": "wrong"}, {"claims": [], "gaps": []}])
    assert not service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "问题").claims
    assert len(calls) == 2


def test_invalid_json_stops_after_two_attempts(mock_service, english_pdf):
    service, calls = mock_service(["bad JSON", "still bad JSON"])
    with pytest.raises(AnalysisError, match="一次格式修复"):
        service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "问题")
    assert len(calls) == 2


def test_invalid_quote_does_not_trigger_repair(mock_service, english_pdf):
    service, calls = mock_service([single_result("THIS IS NOT IN THE PDF")])
    analysis = service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "问题")
    assert not analysis.claims[0].supported
    assert len(calls) == 1


@pytest.mark.parametrize("status,message", [(401, "鉴权"), (403, "权限"), (429, "限流"),
                                            (404, "不存在"), (400, "拒绝"), (503, "不可用"),
                                            (402, "余额不足"), (422, "拒绝")])
def test_api_errors_are_friendly_and_redacted(status, message, mock_service, english_pdf):
    service, calls = mock_service([status])
    with pytest.raises(AnalysisError, match=message) as error:
        service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "问题")
    assert "test-key-not-real" not in str(error.value)
    assert "PRIVATE" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("error,message", [(httpx.ReadTimeout("private timeout"), "超时"),
                                           (httpx.ConnectError("private connection"), "无法连接")])
def test_timeout_and_connection_no_automatic_retry(error, message, mock_service, english_pdf):
    service, calls = mock_service([error])
    with pytest.raises(AnalysisError, match=message):
        service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "问题")
    assert len(calls) == 1


def test_missing_configuration():
    with pytest.raises(AnalysisError, match="OPENAI_API_KEY"):
        LLMService(Settings(model="model"))
    with pytest.raises(AnalysisError, match="OPENAI_MODEL"):
        LLMService(Settings(api_key="test-only"))


@pytest.mark.parametrize("url", ["ftp://example.com", "https://key@example.com/v1", "https://example.com?key=secret", "https://[invalid"])
def test_bad_base_url(url):
    with pytest.raises(AnalysisError, match="BASE_URL"):
        LLMService(Settings(api_key="test-only", model="test-model", base_url=url))


class FakeAnthropic:
    """只实现 LLMService 用到的两个方法，避免联网。"""

    def __init__(self, outputs):
        self.calls: list[dict] = []
        self.closed = False
        self._outputs = iter(outputs)
        fake = self

        class Messages:
            def create(self, **kwargs):
                fake.calls.append(kwargs)
                return next(fake._outputs)

        self.messages = Messages()

    def close(self):
        self.closed = True


def test_anthropic_protocol_sends_system_separately(english_pdf):
    result = single_result("AI improved task completion time in a small sample.")
    fake = FakeAnthropic([
        SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(result, ensure_ascii=False))],
        )
    ])
    service = LLMService(
        Settings(api_key="test-only", model="claude-x", protocol="anthropic"),
        anthropic_client=fake,
    )
    analysis = service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "AI efficiency?")
    assert analysis.claims[0].supported
    call = fake.calls[0]
    assert call["model"] == "claude-x"
    assert call["max_tokens"] == 4096
    # Messages API 的 system 是独立参数，不能混在对话里。
    assert "PDF 物理页码" in call["system"]
    assert all(message["role"] != "system" for message in call["messages"])


def test_anthropic_concatenates_text_blocks():
    fake = FakeAnthropic([
        SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="text", text="第一段"),
                SimpleNamespace(type="tool_use", text=""),
                SimpleNamespace(type="text", text="第二段"),
            ],
        )
    ])
    service = LLMService(
        Settings(api_key="test-only", model="m", protocol="anthropic"),
        anthropic_client=fake,
    )
    assert service._complete([{"role": "user", "content": "问题"}]) == "第一段第二段"


def test_anthropic_truncated_response_is_reported():
    fake = FakeAnthropic([SimpleNamespace(stop_reason="max_tokens", content=[])])
    service = LLMService(
        Settings(api_key="test-only", model="m", protocol="anthropic"),
        anthropic_client=fake,
    )
    with pytest.raises(AnalysisError, match="长度限制"):
        service._complete([{"role": "user", "content": "问题"}])
