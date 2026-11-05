"""三种真实 SDK 请求契约及分块 SSE 测试；不访问外部模型。"""

import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from openai import OpenAI

import llm_service
from config import Settings
from conftest import comparison_result, plan_result, single_result
from llm_service import AnalysisError, LLMService
from pdf_utils import parse_pdf
from workflow import input_signature, run_workflow

PROTOCOLS = ("chat", "responses", "messages")
MESSAGES = [{"role": "system", "content": "只输出 JSON"}, {"role": "user", "content": "研究问题"}]
TEXT = '{"回答":"中文跨字节分块"}'


class FragmentedStream(httpx.SyncByteStream):
    def __init__(self, raw, failure=None):
        self.raw = raw.encode()
        self.failure = failure
        self.closed = False

    def __iter__(self):
        for offset in range(0, len(self.raw), 7):
            yield self.raw[offset:offset + 7]
        if self.failure:
            raise self.failure

    def close(self):
        self.closed = True


def model_response(protocol, text):
    if protocol == "chat":
        return {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}
    if protocol == "responses":
        return {"status": "completed", "output": [{"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    return {"stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": "PRIVATE"}, {"type": "text", "text": text}]}


def stream_response(protocol, text):
    if protocol == "chat":
        events = [("", {"choices": [{"delta": {"reasoning_content": "PRIVATE"}}]}),
                  ("", {"choices": [{"delta": {"content": text[:5]}}]}),
                  ("", {"choices": [{"delta": {"content": text[5:]}}]}),
                  ("", {"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                  ("", {"choices": [], "usage": {"completion_tokens": 20}})]
    elif protocol == "responses":
        events = [("response.output_text.delta", {"delta": text}),
                  ("response.completed", {"response": model_response(protocol, text)})]
    else:
        events = [("message_start", {"message": {"content": []}}),
                  ("content_block_start", {"content_block": {"type": "text", "text": text[:5]}}),
                  ("content_block_delta", {"delta": {"type": "thinking_delta", "thinking": "PRIVATE"}}),
                  ("content_block_delta", {"delta": {"type": "text_delta", "text": text[5:]}}),
                  ("message_delta", {"delta": {"stop_reason": "end_turn"}}),
                  ("message_stop", {})]
    raw = ": keep-alive\r\n\r\n" + "".join(
        (f"event: {name}\r\n" if name else "") + "data: " + json.dumps(event, ensure_ascii=False) + "\r\n\r\n"
        for name, event in events
    )
    return raw + ("data: [DONE]\r\n\r\n" if protocol == "chat" else "")


@pytest.fixture
def gateway(monkeypatch):
    clients = []

    def build(responses, *, protocol="chat", stream=False, base_url="https://gateway.invalid/coding"):
        pending = iter(responses)
        requests = []

        def handle(request):
            requests.append(request)
            output = next(pending)
            if isinstance(output, Exception):
                raise output
            return output

        def create_client(**kwargs):
            client = OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle)))
            clients.append(client)
            return client

        monkeypatch.setattr(llm_service, "OpenAI", create_client)
        settings = Settings(api_key="test-key-not-real", model="test-model", base_url=base_url,
                            protocol=protocol, stream=stream)
        return LLMService(settings), requests

    yield build
    for client in clients:
        client.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("stream", [False, True])
def test_full_workflow_and_json_repair(gateway, protocol, stream, english_pdf, chinese_pdf):
    documents = (parse_pdf(english_pdf, "en.pdf", "D1"), parse_pdf(chinese_pdf, "中文.pdf", "D2"))
    texts = ["invalid JSON"] + [json.dumps(output, ensure_ascii=False) for output in
            [plan_result(), single_result(documents[0].pages[0].text),
             single_result(documents[1].pages[0].text), comparison_result()]]
    responses = [httpx.Response(200, stream=FragmentedStream(stream_response(protocol, text)),
                                headers={"content-type": "text/event-stream"}) if stream
                 else httpx.Response(200, json=model_response(protocol, text)) for text in texts]
    service, requests = gateway(responses, protocol=protocol, stream=stream)
    with service:
        report = run_workflow(documents, "研究问题", service.settings, service=service)
    assert report.coverage_complete
    assert all(analysis.claims[0].supported for analysis in report.analyses)
    assert report.comparison.summary.claim_ids == ("D1-C1", "D2-C1")
    assert len(requests) == 5
    endpoint = {"chat": "chat/completions", "responses": "responses", "messages": "messages"}[protocol]
    for index, request in enumerate(requests):
        assert request.url.path == "/coding/v1/" + endpoint
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["stream"] is stream
        limit = 8192 if index == 4 else 4096
        if protocol == "messages":
            assert request.headers["x-api-key"] == "test-key-not-real"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "authorization" not in request.headers
            assert payload["system"]
            assert all(message["role"] != "system" for message in payload["messages"])
            assert payload["max_tokens"] == limit
        else:
            assert request.headers["authorization"] == "Bearer test-key-not-real"
            assert "x-api-key" not in request.headers
            assert payload["max_output_tokens" if protocol == "responses" else "max_completion_tokens"] == limit
        if protocol == "responses":
            assert payload["store"] is False
    repaired = json.loads(requests[1].content)
    assert len(repaired["input" if protocol == "responses" else "messages"]) == (3 if protocol == "messages" else 4)
    assert all(response.is_closed for response in responses)


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("path,expected", [
    ("", "/v1"), ("/coding/", "/coding/v1"), ("/coding/v1/", "/coding/v1"),
    ("/custom/{endpoint}/", "/custom"), ("/coding/v1/{endpoint}", "/coding/v1"),
])
def test_base_url_normalization(gateway, protocol, path, expected):
    endpoint = {"chat": "chat/completions", "responses": "responses", "messages": "messages"}[protocol]
    service, requests = gateway([httpx.Response(200, json=model_response(protocol, TEXT))],
                                protocol=protocol, base_url="https://gateway.invalid" + path.format(endpoint=endpoint))
    assert service._complete(MESSAGES) == TEXT
    assert requests[0].url.path == expected + "/" + endpoint


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_default_provider(gateway, protocol):
    service, requests = gateway([httpx.Response(200, json=model_response(protocol, TEXT))],
                                protocol=protocol, base_url="")
    assert service._complete(MESSAGES) == TEXT
    assert requests[0].url.host == ("api.anthropic.com" if protocol == "messages" else "api.openai.com")


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("requested_stream", [False, True])
def test_accepts_sse_regardless_of_request_or_content_type(gateway, protocol, requested_stream):
    body = FragmentedStream(stream_response(protocol, TEXT))
    service, requests = gateway([httpx.Response(200, stream=body)], protocol=protocol, stream=requested_stream)
    assert service._complete(MESSAGES) == TEXT
    assert len(requests) == 1
    assert body.closed


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_json_response_to_stream_request(gateway, protocol):
    service, _ = gateway([httpx.Response(200, json=model_response(protocol, TEXT))], protocol=protocol, stream=True)
    assert service._complete(MESSAGES) == TEXT


@pytest.mark.parametrize("protocol,legacy_tokens", [("chat", False), ("chat", True),
                                                    ("responses", False), ("messages", False)])
def test_only_explicit_compatibility_rejections_are_retried(gateway, protocol, legacy_tokens):
    responses = []
    if legacy_tokens:
        responses.append(httpx.Response(400, json={"error": {"message": "Unsupported parameter: max_completion_tokens"}}))
    responses += [httpx.Response(422, json={"error": {"message": "This model requires streaming; stream must be true"}}),
                  httpx.Response(200, stream=FragmentedStream(stream_response(protocol, TEXT)))]
    service, requests = gateway(responses, protocol=protocol)
    assert service._complete(MESSAGES) == TEXT
    payloads = [json.loads(request.content) for request in requests]
    assert len(payloads) == 2 + int(legacy_tokens)
    assert payloads[0]["stream"] is False
    assert payloads[-1]["stream"] is True
    if legacy_tokens:
        assert all(payload["max_tokens"] == 4096 and "max_completion_tokens" not in payload for payload in payloads[1:])


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422, 429, 500])
def test_errors_redacted_without_retry(gateway, protocol, status):
    service, requests = gateway([httpx.Response(status, json={"error": {"message": "PRIVATE test-key-not-real"}})],
                                protocol=protocol)
    with pytest.raises(AnalysisError) as error:
        service._complete(MESSAGES)
    assert "PRIVATE" not in str(error.value)
    assert "test-key-not-real" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("failure,match", [(httpx.ReadTimeout("PRIVATE"), "超时"),
                                          (httpx.ReadError("PRIVATE"), "无法连接")])
def test_stream_transport_failure_closes_response(gateway, protocol, failure, match):
    body = FragmentedStream(": keep-alive\n\n", failure)
    service, requests = gateway([httpx.Response(200, stream=body)], protocol=protocol, stream=True)
    with pytest.raises(AnalysisError, match=match):
        service._complete(MESSAGES)
    assert body.closed
    assert len(requests) == 1


@pytest.mark.parametrize("protocol,raw,match", [
    ("chat", 'data: {invalid}\n\n', "流式响应格式不正确"),
    ("chat", 'data: []\n\n', "流式响应格式不正确"),
    ("chat", 'data: {"choices":[{"delta":{"content":"部分回答"}}]}\n\n', "未完整生成"),
    ("responses", 'data: {"type":"response.output_text.delta","delta":"部分回答"}\n\n', "未完整生成"),
    ("messages", 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n', "未完整生成"),
    ("responses", 'data: [DONE]\n\n', "未完整生成"),
    ("messages", 'data: [DONE]\n\n', "未完整生成"),
    ("chat", 'event: error\ndata: {"error":{"message":"PRIVATE test-key-not-real"}}\n\n', "生成回答时返回错误"),
    ("responses", 'event: response.failed\ndata: {"response":{"error":{"message":"PRIVATE"}}}\n\n', "生成回答时返回错误"),
    ("messages", 'event: error\ndata: {"type":"error","error":{"message":"PRIVATE"}}\n\n', "生成回答时返回错误"),
])
def test_invalid_stream_never_returns_partial_text(gateway, protocol, raw, match):
    body = FragmentedStream(raw)
    service, requests = gateway([httpx.Response(200, stream=body)], protocol=protocol)
    with pytest.raises(AnalysisError, match=match) as error:
        service._complete(MESSAGES)
    assert "PRIVATE" not in str(error.value)
    assert len(requests) == 1
    assert body.closed


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("stream", [False, True])
def test_output_limits_reject_truncated_results(gateway, protocol, stream):
    stop = {"chat": "length", "responses": "incomplete", "messages": "max_tokens"}[protocol]
    if stream:
        raw = stream_response(protocol, TEXT).replace({"chat": '"stop"', "responses": "completed", "messages": "end_turn"}[protocol],
                                                      json.dumps(stop) if protocol == "chat" else stop)
        response = httpx.Response(200, stream=FragmentedStream(raw))
    else:
        result = model_response(protocol, TEXT)
        if protocol == "chat":
            result["choices"][0]["finish_reason"] = stop
        else:
            result["status" if protocol == "responses" else "stop_reason"] = stop
        response = httpx.Response(200, json=result)
    service, requests = gateway([response], protocol=protocol, stream=stream)
    with pytest.raises(AnalysisError, match="长度限制"):
        service._complete(MESSAGES)
    assert len(requests) == 1


@pytest.mark.parametrize("raw,match", [(" \r\n\t", "空响应"), ("<html>PRIVATE</html>", "不是 JSON"),
                                      ("null", "协议不兼容"), ('{"choices":"wrong"}', "协议不兼容")])
def test_bad_gateway_response(gateway, raw, match):
    service, _ = gateway([httpx.Response(200, stream=FragmentedStream(raw))])
    with pytest.raises(AnalysisError, match=match):
        service._complete(MESSAGES)


def test_multiline_sse_and_eof_without_blank_line(gateway):
    raw = ': heartbeat\r\n\r\ndata: {\r\ndata: "choices":[{"delta":{"content":[{"type":"text","text":"中文"}]}}]\r\ndata: }\r\n\r\n'
    raw += 'data: {"choices":[{"finish_reason":"stop","delta":{}}]}'
    service, _ = gateway([httpx.Response(200, stream=FragmentedStream(raw))])
    assert service._complete(MESSAGES) == "中文"


@pytest.mark.parametrize("protocol", ["responses", "messages"])
def test_terminal_stream_event_does_not_wait_for_connection_close(gateway, protocol):
    body = FragmentedStream(stream_response(protocol, TEXT), httpx.ReadTimeout("PRIVATE"))
    service, _ = gateway([httpx.Response(200, stream=body)], protocol=protocol)
    assert service._complete(MESSAGES) == TEXT
    assert body.closed


def test_responses_stream_without_final_text_snapshot(gateway):
    raw = 'event: response.output_text.delta\ndata: ' + json.dumps({"delta": TEXT}) + '\n\n'
    raw += 'event: response.completed\ndata: {"response":{"output":[{"type":"reasoning"}]}}\n\n'
    service, _ = gateway([httpx.Response(200, stream=FragmentedStream(raw))], protocol="responses")
    assert service._complete(MESSAGES) == TEXT


@pytest.mark.parametrize("protocol,result", [
    ("chat", {"choices": [{"finish_reason": "content_filter", "message": {"content": TEXT}}]}),
    ("chat", {"choices": [{"message": {"content": TEXT, "refusal": "PRIVATE"}}]}),
    ("responses", {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "refusal", "refusal": "PRIVATE"}]}]}),
    ("messages", {"stop_reason": "refusal", "content": [{"type": "text", "text": TEXT}]}),
])
def test_refusals_are_not_treated_as_answers(gateway, protocol, result):
    service, _ = gateway([httpx.Response(200, json=result)], protocol=protocol)
    with pytest.raises(AnalysisError, match="未能处理") as error:
        service._complete(MESSAGES)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_empty_text_is_rejected(gateway, protocol):
    service, _ = gateway([httpx.Response(200, json=model_response(protocol, ""))], protocol=protocol)
    with pytest.raises(AnalysisError, match="未返回可读取的文本"):
        service._complete(MESSAGES)


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_redirect_is_not_followed_with_model_credentials(gateway, protocol):
    service, requests = gateway([httpx.Response(307, headers={"location": "https://other.invalid/v1/messages"})],
                                protocol=protocol)
    with pytest.raises(AnalysisError, match="HTTP 307"):
        service._complete(MESSAGES)
    assert len(requests) == 1


def test_compatibility_retry_retains_stream_when_legacy_tokens_are_rejected_second(gateway):
    service, requests = gateway([
        httpx.Response(400, json={"error": {"message": "stream must be true"}}),
        httpx.Response(422, json={"error": {"message": "max_completion_tokens is not supported"}}),
        httpx.Response(200, stream=FragmentedStream(stream_response("chat", TEXT))),
    ])
    assert service._complete(MESSAGES) == TEXT
    payloads = [json.loads(request.content) for request in requests]
    assert len(payloads) == 3
    assert payloads[-1]["stream"] is True
    assert payloads[-1]["max_tokens"] == 4096
    assert "max_completion_tokens" not in payloads[-1]


def test_protocol_separates_workflow_cache_but_stream_transport_does_not(settings):
    signature = input_signature((), "问题", settings)
    legacy_payload = {"documents": [], "question": "问题", "model": settings.model,
                      "base_url": settings.base_url, "prompt_version": 3,
                      "credential_fingerprint": hashlib.sha256(settings.api_key.encode()).hexdigest()}
    assert signature == hashlib.sha256(json.dumps(legacy_payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert signature != input_signature((), "问题", replace(settings, protocol="messages"))
    assert signature == input_signature((), "问题", replace(settings, stream=True))


def test_bad_protocol_is_rejected_before_client_creation():
    with pytest.raises(AnalysisError, match="OPENAI_PROTOCOL"):
        LLMService(Settings(api_key="test-only", model="test-model", protocol="unknown"))
