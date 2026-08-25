from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from hansard.adapters.summarization.openai_compat import (
    EndpointUnreachableError,
    OpenAiCompatibleGenerator,
    StructuredMode,
    join_url,
)
from hansard.adapters.summarization.prompts import MAP_SCHEMA
from hansard.domain.errors import SummarizationError
from hansard.ports.summarization import TextGenerator

ANSWER = {"choices": [{"message": {"content": '{"summary": "ok", "decisions": []}'}}]}


class Recorder:
    def __init__(self, responder) -> None:
        self.requests: list[dict[str, object]] = []
        self.headers: list[httpx.Headers] = []
        self.responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(request.headers)
        body = json.loads(request.read() or b"{}") if request.method == "POST" else {}
        self.requests.append(body)
        return self.responder(len(self.requests), body, request)


def _generator(recorder, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    return OpenAiCompatibleGenerator(http_client=client, sleep=lambda _: None, **kwargs)


def test_generator_satisfies_the_port():
    generator = _generator(Recorder(lambda *_: httpx.Response(200, json=ANSWER)))
    assert isinstance(generator, TextGenerator)
    assert generator.name == "openai-compatible"
    assert generator.context_tokens == 32_768


def test_json_schema_is_requested_first():
    recorder = Recorder(lambda *_: httpx.Response(200, json=ANSWER))
    generator = _generator(recorder)
    assert generator.complete("system", "user", 256, MAP_SCHEMA) == '{"summary": "ok", "decisions": []}'
    body = recorder.requests[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == MAP_SCHEMA
    assert body["max_tokens"] == 256
    assert body["stream"] is False


def test_downgrade_to_json_object_then_prompt():
    def responder(call, body, request):
        fmt = body.get("response_format", {}).get("type")
        if fmt == "json_schema":
            return httpx.Response(400, text="response_format json_schema is not supported")
        if fmt == "json_object":
            return httpx.Response(400, text="this build does not implement response_format")
        return httpx.Response(200, json=ANSWER)

    recorder = Recorder(responder)
    generator = _generator(recorder)
    generator.complete("system", "user", 128, MAP_SCHEMA)
    assert generator.structured_mode is StructuredMode.PROMPT
    assert len(recorder.requests) == 3
    assert "response_format" not in recorder.requests[2]
    assert "JSON schema" in str(recorder.requests[2]["messages"][1]["content"])
    generator.complete("system", "user", 128, MAP_SCHEMA)
    assert len(recorder.requests) == 4


def test_other_bad_requests_are_reported_not_downgraded():
    recorder = Recorder(lambda *_: httpx.Response(400, text="model 'unknown' not found"))
    generator = _generator(recorder)
    with pytest.raises(SummarizationError, match="answered 400"):
        generator.complete("system", "user", 128, MAP_SCHEMA)
    assert len(recorder.requests) == 1


def test_json_is_extracted_from_a_fenced_answer():
    fenced = {"choices": [{"message": {"content": '```json\n{"summary": "ok"}\n```'}}]}
    generator = _generator(Recorder(lambda *_: httpx.Response(200, json=fenced)))
    assert generator.complete("s", "u", 64, MAP_SCHEMA) == '{"summary": "ok"}'


def test_json_is_extracted_from_surrounding_prose():
    noisy = {
        "choices": [
            {"message": {"content": 'Sure, here it is: {"summary": "a} b", "n": {"x": 1}} — hope it helps'}}
        ]
    }
    generator = _generator(Recorder(lambda *_: httpx.Response(200, json=noisy)))
    assert generator.complete("s", "u", 64, MAP_SCHEMA) == '{"summary": "a} b", "n": {"x": 1}}'


def test_answer_without_json_is_an_error():
    prose = {"choices": [{"message": {"content": "I am sorry, I cannot do that."}}]}
    generator = _generator(Recorder(lambda *_: httpx.Response(200, json=prose)))
    with pytest.raises(SummarizationError, match="no JSON object"):
        generator.complete("s", "u", 64, MAP_SCHEMA)


def test_free_text_completion_needs_no_schema():
    prose = {"choices": [{"message": {"content": "Une phrase de synthèse."}}]}
    generator = _generator(Recorder(lambda *_: httpx.Response(200, json=prose)))
    assert generator.complete("s", "u", 64, None) == "Une phrase de synthèse."


def test_api_key_is_sent_but_never_exposed():
    recorder = Recorder(lambda *_: httpx.Response(200, json=ANSWER))
    generator = _generator(recorder, api_key=SecretStr("super-secret"))
    generator.complete("s", "u", 64, None)
    assert recorder.headers[0]["Authorization"] == "Bearer super-secret"
    assert "super-secret" not in repr(generator)
    assert "super-secret" not in str(generator.api_key)


def test_unreachable_endpoint_raises_a_clear_error():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    generator = _generator(refuse)
    with pytest.raises(EndpointUnreachableError) as error:
        generator.complete("s", "u", 64, None)
    message = str(error.value)
    assert "http://localhost:8080/v1" in message
    assert "llama-server" in message


def test_retries_are_attempted_on_transient_failures():
    def responder(call, body, request):
        if call < 3:
            return httpx.Response(503, text="loading model")
        return httpx.Response(200, json=ANSWER)

    recorder = Recorder(responder)
    generator = _generator(recorder)
    generator.complete("s", "u", 64, None)
    assert len(recorder.requests) == 3


def test_probe_reports_a_live_endpoint():
    recorder = Recorder(lambda *_: httpx.Response(200, json={"data": []}))
    assert _generator(recorder).probe() is True


def test_probe_reports_a_dead_endpoint():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    assert _generator(refuse).probe() is False


def test_url_join_is_stable():
    assert join_url("http://host:8080/v1/", "chat/completions") == "http://host:8080/v1/chat/completions"
    assert join_url("http://host:8080/v1", "models") == "http://host:8080/v1/models"
