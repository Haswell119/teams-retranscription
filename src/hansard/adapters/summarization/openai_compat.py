from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum

import httpx
from pydantic import SecretStr

from hansard.adapters.delivery.retry import RetryPolicy, retry_after_seconds
from hansard.adapters.summarization.structured import extract_json_object
from hansard.domain.errors import SummarizationError

CHAT_COMPLETIONS_PATH = "chat/completions"
MODELS_PATH = "models"
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
STRUCTURED_OUTPUT_HINTS = ("response_format", "json_schema", "guided", "grammar", "schema")
UNREACHABLE_GUIDANCE = (
    "start a local OpenAI-compatible server (llama.cpp llama-server, Ollama, vLLM, LM Studio, TGI) "
    "or point HANSARD_MINUTES__ENDPOINT at the machine that runs it"
)
DEFAULT_ENDPOINT = "http://localhost:8080/v1"
DEFAULT_MODEL_ID = "qwen3-8b-instruct"
ENGINE_NAME = "openai-compatible"

Sleeper = Callable[[float], None]
Clock = Callable[[], float]


class EndpointUnreachableError(SummarizationError):
    pass


class StructuredMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT = "prompt"


DOWNGRADES: Mapping[StructuredMode, StructuredMode] = {
    StructuredMode.JSON_SCHEMA: StructuredMode.JSON_OBJECT,
    StructuredMode.JSON_OBJECT: StructuredMode.PROMPT,
}


@contextmanager
def http_session(client: httpx.Client | None, timeout: httpx.Timeout) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
        return
    owned = httpx.Client(timeout=timeout, follow_redirects=False)
    try:
        yield owned
    finally:
        owned.close()


def join_url(endpoint: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}/{path}"


def mentions_structured_output(body: str) -> bool:
    lowered = body.lower()
    return any(hint in lowered for hint in STRUCTURED_OUTPUT_HINTS)


def response_format_for(mode: StructuredMode, schema: dict[str, object], name: str) -> dict[str, object]:
    if mode is StructuredMode.JSON_SCHEMA:
        return {
            "type": "json_schema",
            "json_schema": {"name": name, "schema": schema, "strict": True},
        }
    return {"type": "json_object"}


def schema_instruction(schema: dict[str, object]) -> str:
    return (
        "\n\nAnswer with a single JSON object, with no prose and no code fence, "
        "matching this JSON schema:\n" + json.dumps(schema, ensure_ascii=False)
    )


def first_choice_text(payload: object) -> str:
    if not isinstance(payload, Mapping):
        raise SummarizationError("model endpoint returned a body that is not a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SummarizationError(f"model endpoint returned no choices: {str(payload)[:200]}")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise SummarizationError("model endpoint returned a malformed choice")
    message = first.get("message")
    content = message.get("content") if isinstance(message, Mapping) else first.get("text")
    if isinstance(content, str) and content.strip():
        return content
    raise SummarizationError("model endpoint returned an empty completion")


@dataclass(slots=True)
class OpenAiCompatibleGenerator:
    endpoint: str = DEFAULT_ENDPOINT
    model_id: str = DEFAULT_MODEL_ID
    api_key: SecretStr | None = None
    temperature: float = 0.2
    max_output_tokens: int = 4_096
    context_window: int = 32_768
    timeout_seconds: float = 180.0
    connect_timeout_seconds: float = 5.0
    probe_timeout_seconds: float = 3.0
    http_client: httpx.Client | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Sleeper = time.sleep
    clock: Clock = time.time
    structured_mode: StructuredMode = StructuredMode.JSON_SCHEMA
    schema_name: str = "hansard_minutes"
    extra_headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return ENGINE_NAME

    @property
    def context_tokens(self) -> int:
        return self.context_window

    @property
    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.timeout_seconds, connect=self.connect_timeout_seconds)

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **dict(self.extra_headers)}
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        return headers

    def payload(
        self,
        system: str,
        user: str,
        max_tokens: int,
        schema: dict[str, object] | None,
        mode: StructuredMode,
    ) -> dict[str, object]:
        prompt = user + schema_instruction(schema) if schema and mode is StructuredMode.PROMPT else user
        body: dict[str, object] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": max(1, min(max_tokens, self.max_output_tokens)),
            "stream": False,
        }
        if schema is not None and mode is not StructuredMode.PROMPT:
            body["response_format"] = response_format_for(mode, schema, self.schema_name)
        return body

    def complete(self, system: str, user: str, max_tokens: int, schema: dict[str, object] | None) -> str:
        mode = self.structured_mode if schema is not None else StructuredMode.PROMPT
        url = join_url(self.endpoint, CHAT_COMPLETIONS_PATH)
        with http_session(self.http_client, self.timeout) as client:
            while True:
                response = self._send(client, url, self.payload(system, user, max_tokens, schema, mode))
                downgraded = self._downgrade(response, mode)
                if downgraded is not None:
                    mode = downgraded
                    self.structured_mode = downgraded
                    continue
                text = first_choice_text(self._decode(response))
                return self._as_json(text) if schema is not None else text

    def probe(self) -> bool:
        timeout = httpx.Timeout(self.probe_timeout_seconds, connect=self.connect_timeout_seconds)
        try:
            with http_session(self.http_client, timeout) as client:
                response = client.get(join_url(self.endpoint, MODELS_PATH), headers=self.headers())
        except httpx.HTTPError:
            return False
        return response.status_code < httpx.codes.INTERNAL_SERVER_ERROR

    def _as_json(self, text: str) -> str:
        extracted = extract_json_object(text)
        if extracted is None:
            raise SummarizationError(f"model answer contains no JSON object: {text[:200]!r}")
        return extracted

    def _downgrade(self, response: httpx.Response, mode: StructuredMode) -> StructuredMode | None:
        if response.status_code != httpx.codes.BAD_REQUEST or mode is StructuredMode.PROMPT:
            return None
        if not mentions_structured_output(response.text):
            return None
        return DOWNGRADES[mode]

    def _decode(self, response: httpx.Response) -> object:
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise SummarizationError(
                f"model endpoint {self.endpoint} answered {response.status_code}: {response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as error:
            raise SummarizationError(f"model endpoint returned invalid JSON: {error}") from error

    def _send(self, client: httpx.Client, url: str, body: dict[str, object]) -> httpx.Response:
        headers = self.headers()
        last_error: httpx.HTTPError | None = None
        for attempt in range(max(1, self.retry_policy.attempts)):
            final = attempt == max(1, self.retry_policy.attempts) - 1
            try:
                response = client.post(url, json=body, headers=headers)
            except httpx.HTTPError as error:
                last_error = error
                if final:
                    break
                self.sleep(self.retry_policy.backoff_for(attempt))
                continue
            if response.status_code not in RETRYABLE_STATUS_CODES or final:
                return response
            self.sleep(self._delay_for(response, attempt))
        raise EndpointUnreachableError(
            f"cannot reach the local model endpoint {self.endpoint}: "
            f"{type(last_error).__name__}: {last_error} — {UNREACHABLE_GUIDANCE}"
        )

    def _delay_for(self, response: httpx.Response, attempt: int) -> float:
        advertised = retry_after_seconds(response, self.clock)
        if advertised is None:
            return self.retry_policy.backoff_for(attempt)
        return min(advertised, self.retry_policy.max_retry_after_seconds)
