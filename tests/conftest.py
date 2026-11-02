"""测试 PDF 全部在内存中生成，不使用真实论文或密钥。"""

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_pdf(texts: list[str], *, chinese: bool = False, **save_options) -> bytes:
    with pymupdf.open() as pdf:
        for text in texts:
            page = pdf.new_page()
            if text:
                page.insert_text((50, 70), text, fontname="china-s" if chinese else "helv", fontsize=11)
        return pdf.tobytes(**save_options)


@pytest.fixture
def english_pdf():
    return make_pdf(["AI improved task completion time in a small sample.", "Long-term retention was not measured."])


@pytest.fixture
def chinese_pdf():
    return make_pdf(["生成式人工智能能够提高任务完成效率。", "研究未测量长期学习效果。"], chinese=True)


def single_result(quote: str, *, page: int = 1):
    return {"claims": [{"claim": "研究报告了与问题相关的结果。", "explanation": "结果限于该研究范围。",
                        "evidence": [{"page": page, "quote": quote}]}], "gaps": ["长期效果未充分讨论。"]}


def plan_result():
    return {"tasks": [{"title": "研究问题的直接回答与文献依据", "kind": "evidence"}]}


def comparison_result(ids=("D1-C1", "D2-C1")):
    finding = {"text": "文献在特定条件下报告效率改善，长期效果仍待研究。",
               "claim_ids": list(ids), "basis": "inference"}
    return {"summary": finding,
            "agreements": [{"text": "两篇文献均讨论任务效率。", "claim_ids": list(ids), "basis": "reported"}],
            "answers": [{"task_id": "Q1", "status": "answered", "missing_requirements": [], "caveats": "", "statements": [finding]}],
            "disagreements": [], "method_differences": [], "reasons": [],
            "unresolved_questions": ["长期学习效果如何？"]}


@pytest.fixture
def settings():
    from config import Settings
    return Settings(api_key="test-key-not-real", model="mock-model")


@pytest.fixture
def mock_service(settings):
    """经真正的 OpenAI SDK 发送到 httpx 内存传输层，不访问网络。"""
    import json
    import httpx
    from openai import OpenAI
    from llm_service import LLMService

    clients = []

    def build(responses):
        pending = iter(responses)
        calls = []

        def handle(request):
            calls.append(json.loads(request.content))
            assert request.url.path == "/v1/chat/completions"
            output = next(pending)
            if isinstance(output, Exception):
                raise output
            if isinstance(output, int):
                return httpx.Response(output, json={"error": {"message": "test-key-not-real PRIVATE", "type": "test_error"}})
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
                "model": "mock-model", "choices": [{"index": 0, "finish_reason": "stop",
                                                     "message": {"role": "assistant", "content": text}}]})

        client = OpenAI(api_key=settings.api_key, base_url="https://mock.invalid/v1", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        clients.append(client)
        return LLMService(settings, client=client), calls

    yield build
    for client in clients:
        client.close()
