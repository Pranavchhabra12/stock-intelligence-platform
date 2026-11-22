"""Gemini API client: one JSON-in, JSON-out call, with retries and request spacing.

Only the REST endpoint is used (no SDK), so the request is explicit and easy to
test. Output is requested as JSON matching a schema and is parsed and validated
by the caller; the model's text is never trusted as-is.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.providers.market_data.base import ProviderError
from backend.providers.retry import CallPolicy

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Error text naming the long-standing JSON-output fields (either spelling)
_OLD_FIELDS = re.compile(r"response_?mime_?type|response_?json_?schema", re.I)
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


@dataclass(frozen=True)
class AiResult:
    data: dict[str, Any]
    model: str
    input_tokens: int | None
    output_tokens: int | None


class GeminiClient:
    source_code = "gemini"

    def __init__(
        self, api_key: str, model: str, client: httpx.Client | None = None,
        min_interval_seconds: float = 5.0, max_attempts: int = 3, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("a Gemini API key is required")
        self.model = model
        self._key = api_key
        self.client = client or httpx.Client(timeout=120)
        # Free-tier limits are a few requests a minute; spacing calls avoids most 429s,
        # and a 429 is retried after 15s, then 30s.
        self.policy = CallPolicy(self.source_code, min_interval_seconds, max_attempts, sleep, backoff_base=15.0)
        # Gemini has two ways to ask for JSON output. The long-standing one
        # (responseMimeType + responseJsonSchema) is tried first; if the API rejects it,
        # the newer responseFormat block is used from then on.
        self._new_format = False
        self.requests_made = 0

    def _body(self, system: str, prompt: str, schema: dict) -> dict:
        config: dict[str, Any] = {"temperature": 0.2}
        if self._new_format:
            config["responseFormat"] = {"text": {"mimeType": "application/json", "schema": schema}}
        else:
            config |= {"responseMimeType": "application/json", "responseJsonSchema": schema}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }

    def _post(self, system: str, prompt: str, schema: dict) -> dict:
        url = f"{API_BASE}/models/{self.model}:generateContent"
        self.requests_made += 1
        response = self.client.post(url, json=self._body(system, prompt, schema), headers={"x-goog-api-key": self._key})
        if response.status_code == 400 and not self._new_format and _OLD_FIELDS.search(response.text):
            logger.info("gemini_structured_output_fallback")
            self._new_format = True
            return self._post(system, prompt, schema)
        if response.status_code in (400, 401, 403, 404):
            # Bad request, bad key or unknown model: retrying won't help. The body never contains the key.
            raise ProviderError(f"gemini: HTTP {response.status_code}: {_error_message(response)}")
        response.raise_for_status()   # 429 and 5xx are retried by the call policy
        return response.json()

    def generate_json(self, system: str, prompt: str, schema: dict) -> AiResult:
        payload = self.policy.call("generate", self.model, lambda: self._post(system, prompt, schema))
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ProviderError(f"gemini: no answer ({reason})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        raw = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not raw.strip():
            raise ProviderError(f"gemini: empty answer ({candidates[0].get('finishReason', 'unknown')})")
        try:
            data = json.loads(_FENCE.sub("", raw))
        except json.JSONDecodeError:
            raise ProviderError("gemini: answer was not valid JSON") from None
        if not isinstance(data, dict):
            raise ProviderError("gemini: answer was not a JSON object")
        usage = payload.get("usageMetadata") or {}
        return AiResult(data, self.model, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError):
        return response.text[:300]
