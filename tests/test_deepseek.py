"""DeepSeek 的 SDK 请求契约测试：网络请求由内存传输替代。"""

import json

import httpx
import pytest
from openai import OpenAI

from config import Settings
from conftest import comparison_result, plan_result, single_result
from llm_service import LLMService
from pdf_utils import parse_pdf
from workflow import run_workflow


@pytest.mark.parametrize("base_url,path", [
    ("https://api.deepseek.com", "/chat/completions"),
    ("https://api.deepseek.com/v1", "/v1/chat/completions"),
])
def test_deepseek_full_sdk_workflow(base_url, path, english_pdf, chinese_pdf):
    settings = Settings(api_key="deepseek-test-not-real", base_url=base_url, model="deepseek-flash")
    documents = (parse_pdf(english_pdf, "en.pdf", "D1"), parse_pdf(chinese_pdf, "中文.pdf", "D2"))
    outputs = iter([plan_result()] + [single_result(d.pages[0].text) for d in documents] + [comparison_result()])
    requests = []

    def handle(request):
        assert request.url.host == "api.deepseek.com"
        assert request.url.path == path
        assert request.headers["Authorization"] == "Bearer deepseek-test-not-real"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "deepseek-flash"
        assert body["thinking"] == {"type": "disabled"}
        payload = json.loads(body["messages"][1]["content"])
        assert body["max_tokens"] == (8192 if "documents" in payload else 4096)
        assert "response_format" not in body  # 仍保留通用 JSON 解析及有限修复
        return httpx.Response(200, json={
            "id": "deepseek-test", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(next(outputs), ensure_ascii=False),
            }}],
        })

    with OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
        report = run_workflow(documents, "AI 是否提高学习效率？", settings,
                              service=LLMService(settings, client=client))
    assert len(requests) == 4
    assert report.coverage_complete
    assert all(a.claims[0].supported for a in report.analyses)
    assert report.comparison.summary.claim_ids == ("D1-C1", "D2-C1")


@pytest.mark.parametrize("url", ["https://api.deepseek.com.evil.example", "https://other-provider.example/v1", "", "https://[invalid"])
def test_deepseek_detection_uses_exact_hostname(url):
    assert not Settings(base_url=url).is_deepseek


def test_generic_provider_receives_no_deepseek_parameters(mock_service, english_pdf):
    service, requests = mock_service([single_result("AI improved task completion time in a small sample.")])
    service.analyze_document(parse_pdf(english_pdf, "study.pdf", "D1"), "AI efficiency?")
    assert "thinking" not in requests[0]
    assert "max_tokens" not in requests[0]
