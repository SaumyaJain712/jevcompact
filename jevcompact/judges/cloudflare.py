"""Cloudflare Workers AI judge: a free stand-in for Jev.

Implements the same Judge protocol as JevJudge. Each request carries the same
state and the same yes/no questions that would go to Jev; a chat model on
Workers AI is asked to return strict JSON

    {"scores": {"<question id>": <probability that the answer is yes, 0..1>, ...}}

with temperature 0. A reply that is not valid JSON, misses an id or has a
value outside [0, 1] is retried once; a second bad reply raises JudgeError,
which the pipeline treats exactly like a Jev failure (plain-summary fallback).

Model choice (docs/measurements/judge_model_bakeoff.json, held-out probe):
IBM Granite 4.0 micro, the cheapest Workers AI chat model (1,542 neurons per M
input tokens). It returned valid JSON on every request and found every needed
item once each question line also shows the item's title next to its id
(without the title, every model tried answered 0 for every item). GLM-4.7-flash
answers 0 for everything with its reasoning off; with reasoning on it works but
costs ~6x more per request and often took longer than 60 s. A constrained
`response_format` JSON schema is not sent for GLM: it suppressed the reasoning.

The scores are a language model's stated probabilities, not Jev's calibrated
noul values, so the keep / drop thresholds are re-tuned with the threshold
sweep in eval/ (see PROGRESS.md, design deviations).

Same account and token as the summarizer (CF_ACCOUNT_ID, CF_API_TOKEN). Cost is
reported in neurons (free tier: 10,000 per day), computed from the model's
token usage with the pricing table below.

REST: POST https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re

import httpx

from .base import JudgeError, JudgeResponse, Question

log = logging.getLogger(__name__)

# Per model: neurons per million input / output tokens, context window, and how
# JSON output is requested. Sources (read 2026-11-24): the models API
# (/ai/models/search, /ai/models/schema) and
# developers.cloudflare.com/workers-ai/platform/pricing/.
#   json = "openai":  response_format {"type": "json_schema", "json_schema": {"name", "schema", "strict"}}
#   json = "workers": response_format {"type": "json_schema", "json_schema": <schema>}  (Workers AI JSON mode)
#   json = None:      no JSON mode; the prompt alone asks for JSON
JUDGE_MODELS: dict[str, dict] = {
    # Reasoning model: its reasoning tokens are billed as output. Works, but ~6x Granite's cost.
    "@cf/zai-org/glm-4.7-flash": {"in": 5_500, "out": 36_400, "context": 131_072, "json": None,
                                  "max_param": "max_completion_tokens", "reasoning": True},
    # Same, reasoning off: valid JSON but scores every item 0 (kept for the bake-off only).
    "@cf/zai-org/glm-4.7-flash:no-reasoning": {"in": 5_500, "out": 36_400, "context": 131_072, "json": None,
                                               "max_param": "max_completion_tokens", "reasoning": False},
    # Default (chosen by the bake-off in docs/measurements/judge_model_bakeoff.json).
    "@cf/ibm-granite/granite-4.0-h-micro": {"in": 1_542, "out": 10_158, "context": 131_000, "json": "workers",
                                            "family": "Granite"},
    # Needs a licence agreement accepted on the account first (not done; not tested).
    "@cf/meta/llama-3.2-11b-vision-instruct": {"in": 4_410, "out": 61_493, "context": 128_000, "json": None},
}
DEFAULT_JUDGE_MODEL = "@cf/ibm-granite/granite-4.0-h-micro"


def judge_label(model: str) -> str:
    """How every table, chart and the README name this judge."""
    family = JUDGE_MODELS.get(model, {}).get("family") or ("GLM" if "glm" in model else model.split("/")[-1])
    return f"Cloudflare ({family}) judge, standing in for Jev"

SYSTEM_PROMPT = (
    "You are a strict yes/no judge. The user message contains a STATE and then QUESTIONS, one per line, "
    "each starting with its id. Answer every question using only the STATE. For each id give the probability "
    "that the true answer is yes, as a number from 0 to 1 (1 = certainly yes, 0 = certainly no, 0.5 = cannot tell). "
    'Reply with only one JSON object of the form {"scores": {"<id>": <number>, ...}} that contains every '
    "question id exactly once. No other keys, no explanations, no markdown."
)

RETRY_HTTP = {429, 500, 502, 503, 504}


class InvalidJudgeReply(ValueError):
    """The model's reply was not the strict JSON we asked for."""


def parse_scores(raw: object, ids: list[str]) -> dict[str, float]:
    """Parse and validate a reply. Raises InvalidJudgeReply unless every id has a number in [0, 1]."""
    if isinstance(raw, str):
        text = re.sub(r"(?s)<think>.*?</think>", "", raw).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()  # tolerate a code fence, nothing else
        try:
            raw = json.loads(text)
        except ValueError as exc:
            raise InvalidJudgeReply(f"not JSON: {text[:80]!r}") from exc
    if not isinstance(raw, dict):
        raise InvalidJudgeReply(f"expected a JSON object, got {type(raw).__name__}")
    scores = raw.get("scores")
    if not isinstance(scores, dict):
        raise InvalidJudgeReply('missing "scores" object')
    out: dict[str, float] = {}
    for qid in ids:
        v = scores.get(qid)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise InvalidJudgeReply(f"id {qid!r}: {v!r} is not a number from 0 to 1")
        out[qid] = float(v)
    return out


class CloudflareJudge:
    name = "cloudflare"

    def __init__(self, account_id: str, api_token: str, model: str = DEFAULT_JUDGE_MODEL,
                 max_request_tokens: int = 16_000, http_timeout_s: float = 60.0,
                 client: httpx.AsyncClient | None = None):
        if not account_id or not api_token:
            raise JudgeError("CF_ACCOUNT_ID and CF_API_TOKEN must be set for the Cloudflare judge")
        self.account_id = account_id
        self._token = api_token
        self.spec = JUDGE_MODELS.get(model, {"json": None})
        self.model = model.split(":")[0]  # ":no-reasoning" is a bake-off variant of the same model
        # Read by jevcompact.batching callers: an LLM is slower than Jev, so requests are
        # smaller than Jev's 32k and the per-request timeout covers one retry.
        self.max_request_tokens = max_request_tokens
        self.http_timeout_s = http_timeout_s
        self.request_timeout_s = 2 * http_timeout_s + 5
        self._client = client

    def __repr__(self) -> str:  # never show the token
        return f"CloudflareJudge(model={self.model!r})"

    @classmethod
    def from_config(cls, config) -> "CloudflareJudge":
        return cls(config.cf_account_id or "", config.cf_api_token or "", config.cf_judge_model,
                   config.cf_judge_max_request_tokens)

    @property
    def url(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{self.model}"

    def neurons(self, in_tokens: int, out_tokens: int) -> float:
        n_in, n_out = self.spec.get("in"), self.spec.get("out")
        if n_in is None:
            return 0.0
        return round(in_tokens * n_in / 1e6 + out_tokens * n_out / 1e6, 3)

    @staticmethod
    def user_prompt(state: str, questions: list[Question]) -> str:
        # The question text is exactly Jev's; the item title (when known) is shown next to
        # the id so the model can find the item in a long state.
        def line(q: Question) -> str:
            title = q.meta.get("title")
            return f"{q.id} ({title}): {q.text}" if title else f"{q.id}: {q.text}"

        qs = "\n".join(line(q) for q in questions)
        return f"STATE:\n{state}\n\nQUESTIONS:\n{qs}"

    def body(self, state: str, questions: list[Question]) -> dict:
        ids = [q.id for q in questions]
        body: dict = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": self.user_prompt(state, questions)}],
            "temperature": 0,
        }
        if self.spec.get("reasoning"):  # room for the reasoning, which comes before the JSON
            body[self.spec["max_param"]] = min(16_000, 4_000 + 40 * len(ids))
        else:
            body[self.spec.get("max_param", "max_tokens")] = 64 + 14 * len(ids)
        schema = {"type": "object", "additionalProperties": False, "required": ["scores"],
                  "properties": {"scores": {"type": "object", "additionalProperties": False, "required": ids,
                                            "properties": {i: {"type": "number", "minimum": 0, "maximum": 1}
                                                           for i in ids}}}}
        if self.spec.get("json") == "openai":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "scores", "schema": schema, "strict": True}}
        elif self.spec.get("json") == "workers":
            body["response_format"] = {"type": "json_schema", "json_schema": schema}
        if self.spec.get("reasoning") is False:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        return body

    async def _post(self, client: httpx.AsyncClient, body: dict) -> dict:
        for attempt in range(2):
            try:
                resp = await client.post(self.url, json=body, headers={"Authorization": f"Bearer {self._token}"})
            except httpx.TimeoutException as exc:
                raise JudgeError(f"Cloudflare judge didn't respond in {self.http_timeout_s:g} s") from exc
            except httpx.HTTPError as exc:
                raise JudgeError(f"Could not reach Cloudflare Workers AI: {type(exc).__name__}") from exc
            if resp.status_code in RETRY_HTTP and attempt == 0:
                await asyncio.sleep(1.0)
                continue
            try:
                data = resp.json()
            except ValueError as exc:
                raise JudgeError(f"Cloudflare returned HTTP {resp.status_code} (not JSON)") from exc
            if resp.status_code != 200 or not data.get("success", False):
                errs = "; ".join(str(e.get("message", e)) for e in data.get("errors") or []) or resp.text[:200]
                raise JudgeError(f"Cloudflare returned HTTP {resp.status_code}: {errs}")
            return data.get("result") or {}
        raise JudgeError("unreachable")  # pragma: no cover

    @staticmethod
    def _reply(result: dict) -> object:
        if "response" in result and result["response"] is not None:
            return result["response"]  # Workers AI shape; a dict when JSON mode parsed it already
        try:
            return result["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""

    async def evaluate(self, state: str, questions: list[Question]) -> JudgeResponse:
        ids = [q.id for q in questions]
        body = self.body(state, questions)
        client = self._client or httpx.AsyncClient(timeout=self.http_timeout_s)
        tin = tout = 0
        billed = 0.0
        try:
            for attempt in range(2):  # invalid JSON is retried once
                result = await self._post(client, body)
                usage = result.get("usage") or {}
                tin += int(usage.get("prompt_tokens", 0))
                tout += int(usage.get("completion_tokens", 0))
                # Cloudflare reports neurons in usage; fall back to the pricing table.
                billed += float(usage["neurons"]) if usage.get("neurons") is not None else \
                    self.neurons(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
                try:
                    scores = parse_scores(self._reply(result), ids)
                except InvalidJudgeReply as exc:
                    log.warning("Cloudflare judge reply invalid (attempt %d): %s", attempt + 1, exc)
                    if attempt == 0:
                        continue
                    err = JudgeError(f"Cloudflare judge returned invalid JSON twice: {exc}")
                    err.neurons = round(billed, 3)  # spent anyway; the eval's neuron ledger counts it
                    raise err from exc
                return JudgeResponse(scores, tin, tout, self.model, neurons=round(billed, 3), attempts=attempt + 1)
        finally:
            if self._client is None:
                await client.aclose()
        raise JudgeError("unreachable")  # pragma: no cover

    async def test_connection(self) -> bool:
        await self.evaluate("The sky is blue.", [Question("q", "keep", "Is the sky blue?")])
        return True
