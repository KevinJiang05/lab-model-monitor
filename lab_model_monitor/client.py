from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import sleep
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from lab_model_monitor import __version__

DEFAULT_GPT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-5.6-luna",
    "api_mode": "responses",
    "timeout_seconds": 30.0,
}

JsonRequester = Callable[[str, Mapping[str, str], bytes, float], Any]
JsonGetter = Callable[[str, Mapping[str, str], float], Any]
_STREAM_RETRY_BACKOFF_SECONDS = 3.0


class GPTAPIError(RuntimeError):
    """A secret-safe error raised at the configurable GPT provider boundary."""


@dataclass(frozen=True)
class GPTClientConfig:
    base_url: str
    model: str
    api_mode: str = "responses"
    timeout_seconds: float = 30.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> GPTClientConfig:
        values = {**DEFAULT_GPT_SETTINGS, **dict(payload or {})}
        base_url = normalize_openai_base_url(str(values["base_url"]))
        model = str(values["model"] or "").strip()
        if not model or len(model) > 200:
            raise ValueError("GPT model must be a non-empty value of at most 200 characters.")
        api_mode = str(values["api_mode"] or "").strip().casefold()
        if api_mode not in {"responses", "chat_completions"}:
            raise ValueError("GPT API mode must be responses or chat_completions.")
        timeout_seconds = float(values["timeout_seconds"])
        if not 1 <= timeout_seconds <= 600:
            raise ValueError("GPT request timeout must be between 1 and 600 seconds.")
        return cls(
            base_url=base_url,
            model=model,
            api_mode=api_mode,
            timeout_seconds=timeout_seconds,
        )

    @property
    def request_url(self) -> str:
        suffix = "responses" if self.api_mode == "responses" else "chat/completions"
        return f"{self.base_url}/{suffix}"

    def to_dict(self, *, enabled: bool = False) -> dict[str, Any]:
        return {
            "enabled": bool(enabled),
            "base_url": self.base_url,
            "model": self.model,
            "api_mode": self.api_mode,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class GPTResponse:
    text: str
    model: str
    response_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    sources: tuple[dict[str, str], ...] = ()
    completion_status: str = ""


class OpenAICompatibleClient:
    """Small OpenAI-compatible client with an explicit configurable HTTPS endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        config: GPTClientConfig,
        requester: JsonRequester | None = None,
        model_requester: JsonGetter | None = None,
        retry_stream_failures: bool = True,
    ) -> None:
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ValueError("GPT API key is not configured.")
        self._api_key = normalized_key
        self.config = config
        self._requester = requester or _request_json
        self._model_requester = model_requester or _get_json
        self._retry_stream_failures = retry_stream_failures

    def list_models(self) -> list[dict[str, str]]:
        try:
            response = self._model_requester(
                f"{self.config.base_url}/models",
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                    "User-Agent": f"LabModelMonitor/{__version__}",
                },
                self.config.timeout_seconds,
            )
        except urllib.error.HTTPError as exc:
            raise GPTAPIError(
                f"GPT model endpoint rejected the request with HTTP {int(exc.code)}. "
                "Check the endpoint and key."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GPTAPIError(
                f"GPT model endpoint could not be reached ({type(exc).__name__})."
            ) from None
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise GPTAPIError("GPT model endpoint returned an incompatible response.")
        models: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in response["data"]:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            models.append(
                {
                    "id": model_id,
                    "label": str(item.get("display_name") or model_id).strip(),
                }
            )
        if not models:
            raise GPTAPIError("GPT model endpoint returned no selectable models.")
        return models

    def generate_text(
        self,
        *,
        instructions: str,
        input_text: str,
        web_search: bool = False,
        response_schema: Mapping[str, Any] | None = None,
        schema_name: str = "structured_response",
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> GPTResponse:
        normalized_input = str(input_text or "").strip()
        if not normalized_input:
            raise ValueError("GPT input must not be empty.")
        payload = self._request_payload(
            instructions=str(instructions or "").strip(),
            input_text=normalized_input,
            web_search=web_search,
            response_schema=response_schema,
            schema_name=schema_name,
            reasoning_effort=reasoning_effort,
            max_output_tokens=max_output_tokens,
        )
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            response = self._request_response(encoded)
        except urllib.error.HTTPError as exc:
            raise GPTAPIError(
                f"GPT endpoint rejected the request with HTTP {int(exc.code)}. "
                "Check the endpoint, API mode, model, and key."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GPTAPIError(
                f"GPT endpoint could not be reached ({type(exc).__name__})."
            ) from None
        if not isinstance(response, dict):
            raise GPTAPIError("GPT endpoint returned a non-object JSON response.")
        text = _extract_response_text(response, self.config.api_mode)
        if not text:
            completion_status = _completion_status(response, self.config.api_mode)
            if completion_status in {"incomplete", "length"}:
                raise GPTAPIError(
                    f"GPT response was incomplete (status={completion_status})."
                )
            raise GPTAPIError(
                "GPT endpoint returned no text in the configured API mode. "
                "The relay may not implement that OpenAI-compatible response shape."
            )
        raw_usage = response.get("usage")
        usage: dict[str, Any] = dict(raw_usage) if isinstance(raw_usage, dict) else {}
        return GPTResponse(
            text=text,
            model=str(response.get("model") or self.config.model),
            response_id=str(response.get("id") or ""),
            input_tokens=_optional_int(usage.get("input_tokens", usage.get("prompt_tokens"))),
            output_tokens=_optional_int(
                usage.get("output_tokens", usage.get("completion_tokens"))
            ),
            total_tokens=_optional_int(usage.get("total_tokens")),
            sources=_extract_web_sources(response),
            completion_status=_completion_status(response, self.config.api_mode),
        )

    def _request_response(self, encoded: bytes) -> Any:
        for attempt in range(2):
            try:
                return self._requester(
                    self.config.request_url,
                    {
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": f"LabModelMonitor/{__version__}",
                    },
                    encoded,
                    self.config.timeout_seconds,
                )
            except GPTAPIError as exc:
                if attempt or not self._retry_stream_failures or not _is_retryable_stream_failure(exc):
                    raise
                sleep(_STREAM_RETRY_BACKOFF_SECONDS)
        raise AssertionError("unreachable")

    def _request_payload(
        self,
        *,
        instructions: str,
        input_text: str,
        web_search: bool,
        response_schema: Mapping[str, Any] | None,
        schema_name: str,
        reasoning_effort: str | None,
        max_output_tokens: int | None,
    ) -> dict[str, Any]:
        if reasoning_effort is not None and reasoning_effort not in {
            "none", "minimal", "low", "medium", "high", "xhigh", "max",
        }:
            raise ValueError("Unsupported GPT reasoning effort.")
        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or not 1 <= max_output_tokens <= 128000
        ):
            raise ValueError("GPT output token limit must be an integer from 1 to 128000.")
        if self.config.api_mode == "responses":
            payload: dict[str, Any] = {
                "model": self.config.model,
                "instructions": instructions,
                "input": input_text,
                "store": False,
            }
            if reasoning_effort is not None:
                payload["reasoning"] = {"effort": reasoning_effort}
            if max_output_tokens is not None:
                payload["max_output_tokens"] = max_output_tokens
            if web_search:
                payload["tools"] = [{"type": "web_search"}]
                payload["include"] = ["web_search_call.action.sources"]
            if response_schema is not None:
                normalized_name = str(schema_name or "").strip()
                if not normalized_name or len(normalized_name) > 64:
                    raise ValueError("GPT response schema name must contain 1 to 64 characters.")
                payload["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": normalized_name,
                        "strict": True,
                        "schema": dict(response_schema),
                    }
                }
            return payload
        if web_search or response_schema is not None:
            raise ValueError(
                "Web search and structured output require the Responses API protocol."
            )
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
        }
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        if max_output_tokens is not None:
            payload["max_completion_tokens"] = max_output_tokens
        return payload


def _completion_status(payload: Mapping[str, Any], api_mode: str) -> str:
    if api_mode == "responses":
        return str(payload.get("status") or "")
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return str(choices[0].get("finish_reason") or "")
    return ""


def normalize_openai_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("GPT API endpoint must be an absolute HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("GPT API endpoint must not contain credentials, a query, or a fragment.")
    path = parsed.path.rstrip("/")
    normalized = SplitResult(
        scheme="https",
        netloc=parsed.netloc,
        path=path,
        query="",
        fragment="",
    )
    return urlunsplit(normalized)


def _request_json(
    url: str,
    headers: Mapping[str, str],
    data: bytes,
    timeout_seconds: float,
) -> Any:
    request = urllib.request.Request(
        url,
        data=data,
        headers=dict(headers),
        method="POST",
    )
    with urllib.request.urlopen(  # noqa: S310 - user-configured HTTPS provider endpoint
        request,
        timeout=timeout_seconds,
    ) as response:
        return _load_json_response(response)


def _get_json(
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> Any:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    with urllib.request.urlopen(  # noqa: S310 - user-configured HTTPS provider endpoint
        request,
        timeout=timeout_seconds,
    ) as response:
        return _load_json_response(response)


def _load_json_response(response: Any) -> Any:
    raw = response.read()
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        streamed = _decode_responses_sse(text if "text" in locals() else "")
        if streamed is not None:
            return streamed
        raise GPTAPIError("GPT endpoint returned neither JSON nor compatible Responses SSE.") from exc


def _decode_responses_sse(text: str) -> dict[str, Any] | None:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    for event in reversed(events):
        event_type = str(event.get("type") or "")
        response = event.get("response")
        response_payload = response if isinstance(response, dict) else {}
        if event_type == "response.failed":
            error = response_payload.get("error")
            error_payload = error if isinstance(error, dict) else {}
            code = str(error_payload.get("code") or error_payload.get("type") or "unknown")
            raise GPTAPIError(
                _stream_error_text(
                    prefix="GPT Responses stream failed",
                    code=code,
                    message=error_payload.get("message"),
                )
            )
        if event_type == "response.incomplete":
            details = response_payload.get("incomplete_details")
            details_payload = details if isinstance(details, dict) else {}
            reason = str(details_payload.get("reason") or "unknown")
            raise GPTAPIError(f"GPT Responses stream was incomplete (reason={reason}).")
        if event_type == "error":
            error = event.get("error")
            error_payload = error if isinstance(error, dict) else {}
            code = str(error_payload.get("code") or error_payload.get("type") or "unknown")
            raise GPTAPIError(
                _stream_error_text(
                    prefix="GPT Responses stream returned an error",
                    code=code,
                    message=error_payload.get("message"),
                )
            )

    completed_response: dict[str, Any] | None = None
    for event in reversed(events):
        response = event.get("response")
        if event.get("type") == "response.completed" and isinstance(response, dict):
            completed_response = response
            if _extract_response_text(response, "responses"):
                return response
            break
    deltas = [
        str(event.get("delta"))
        for event in events
        if event.get("type") == "response.output_text.delta"
        and isinstance(event.get("delta"), str)
    ]
    if deltas:
        result = dict(completed_response or {})
        result["output_text"] = "".join(deltas)
        if completed_response is None:
            result["status"] = "incomplete"
        return result
    return completed_response


def _is_retryable_stream_failure(exc: GPTAPIError) -> bool:
    message = str(exc)
    return message.startswith("GPT Responses stream ") or message == (
        "GPT endpoint returned neither JSON nor compatible Responses SSE."
    )


def _stream_error_text(*, prefix: str, code: str, message: object) -> str:
    safe_message = " ".join(str(message or "").split())[:500]
    if safe_message:
        return f"{prefix} (code={code}): {safe_message}"
    return f"{prefix} (code={code})."


def _extract_response_text(payload: Mapping[str, Any], api_mode: str) -> str:
    if api_mode == "chat_completions":
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        return _content_text(message.get("content") if isinstance(message, dict) else None)
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    fragments: list[str] = []
    for item in output:
        if not isinstance(item, dict) or not isinstance(item.get("content"), list):
            continue
        for content in item["content"]:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    fragments.append(text.strip())
    return "\n".join(fragments)


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    fragments = [
        str(item.get("text") or "").strip()
        for item in value
        if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
    ]
    return "\n".join(fragment for fragment in fragments if fragment)


def _extract_web_sources(payload: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    sources: list[dict[str, str]] = []
    output = payload.get("output")
    if not isinstance(output, list):
        return ()
    for item in output:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "web_search_call":
            action = item.get("action")
            if isinstance(action, Mapping):
                _append_sources(sources, action.get("sources"))
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, Mapping):
                continue
            annotations = block.get("annotations")
            if isinstance(annotations, list):
                _append_sources(sources, annotations)
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in sources:
        url = source["url"]
        if url in seen:
            continue
        seen.add(url)
        unique.append(source)
    return tuple(unique)


def _append_sources(target: list[dict[str, str]], value: object) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        target.append(
            {
                "url": url,
                "title": str(item.get("title") or url).strip(),
            }
        )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
