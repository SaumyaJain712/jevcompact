"""Jev (TypeSafe AI) judge client.

API per https://docs.typesafe.ai/api/system-one.md and api.typesafe.ai/openapi.json
(read 2026-11-19):

    POST {base_url}/systemone        Authorization: Bearer <key>
    {"model": "jev-latest", "state": "...",
     "questions": {"<id>": {"type": "noul", "instructions": "<yes/no question>"}}}
    -> {"model": "...", "answers": {"<id>": {"type": "noul", "noul": 0.97}},
        "usage": {"input_tokens": 110, "output_tokens": 10}}

    GET {base_url}/models            lists models (used for "Test connection")

OpenRouter serves the same System One surface at https://openrouter.ai/api/v1
(model "~typesafe/jev-latest"), so JEV_BASE_URL switches between the two.

Errors: 400 (incl. max_tokens_exceeded), 401 bad key, 413, 415, 422 validation,
429 rate limited and 529 overloaded (retry with exponential backoff).

Limits we enforce come from our SRS (TypeSafe models page, Oct 2026): 32k tokens
per request, 80 req/s, 100k tok/s, English only, 5 s timeout. The docs list
64k per request / 32k per question by default, so 32k per request is stricter
and consistent with them. Rate limits are per organisation in the console.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from .base import JudgeError, JudgeResponse, Question

log = logging.getLogger(__name__)
RETRY_STATUSES = {429, 529}


class JevJudge:
    name = "jev"

    def __init__(self, api_key: str, base_url: str = "https://api.typesafe.ai/v1", model: str = "jev-latest",
                 timeout_s: float = 5.0, max_retries: int = 2, client: httpx.AsyncClient | None = None):
        if not api_key:
            raise JudgeError("JEV_API_KEY is not set")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client = client

    def __repr__(self) -> str:  # never show the key
        return f"JevJudge(base_url={self.base_url!r}, model={self.model!r})"

    @classmethod
    def from_config(cls, config) -> "JevJudge":
        return cls(config.jev_api_key or "", config.jev_base_url, config.jev_model, config.jev_timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kw)
                except httpx.TimeoutException as exc:
                    raise JudgeError(f"Jev didn't respond in {self.timeout_s:g} s") from exc
                except httpx.HTTPError as exc:
                    raise JudgeError(f"Could not reach Jev: {type(exc).__name__}") from exc
                if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                    await asyncio.sleep(0.1 * 2 ** attempt)
                    continue
                return resp
        finally:
            if self._client is None:
                await client.aclose()
        raise JudgeError("unreachable")  # pragma: no cover

    @staticmethod
    def _error(resp: httpx.Response) -> JudgeError:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text[:200]
        if resp.status_code == 401:
            return JudgeError("Jev rejected the API key (401)")
        if resp.status_code == 400 and "max_tokens_exceeded" in str(detail):
            return JudgeError("Jev request exceeded the model's context length (max_tokens_exceeded)")
        return JudgeError(f"Jev returned HTTP {resp.status_code}: {str(detail)[:200]}")

    async def evaluate(self, state: str, questions: list[Question]) -> JudgeResponse:
        body = {
            "model": self.model,
            "state": state,
            "questions": {q.id: {"type": "noul", "instructions": q.text} for q in questions},
        }
        resp = await self._request("POST", "/systemone", json=body)
        if resp.status_code != 200:
            raise self._error(resp)
        try:
            data = resp.json()
            answers = data["answers"]
            scores = {q.id: float(answers[q.id]["noul"]) for q in questions}
            usage = data.get("usage") or {}
        except (ValueError, KeyError, TypeError) as exc:
            raise JudgeError(f"Unexpected Jev response: {exc!r}") from exc
        return JudgeResponse(scores, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)),
                             str(data.get("model", "")))

    async def test_connection(self) -> bool:
        resp = await self._request("GET", "/models")
        if resp.status_code != 200:
            raise self._error(resp)
        return True
