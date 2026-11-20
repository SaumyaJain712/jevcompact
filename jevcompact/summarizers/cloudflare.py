"""Cloudflare Workers AI summarizer.

REST (developers.cloudflare.com/workers-ai, read 2026-11-19):

    POST https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}
    Authorization: Bearer {CF_API_TOKEN}
    {"messages": [{"role": "system", ...}, {"role": "user", ...}], "max_tokens": 512, "temperature": 0.2}
    -> {"success": true, "errors": [], "result": {"response": "...", "usage": {...}}}

Llama models return `result.response`; chat-completion models such as
@cf/zai-org/glm-4.7-flash return `result.choices[0].message.content`. Both are
handled. Neurons are computed from usage with the pricing table below
(free tier: 10,000 neurons/day). Input longer than the model's context is split
into parts that are summarized separately and concatenated.
"""
from __future__ import annotations

import re

import httpx

from ..tokens import count_tokens
from .base import SummarizerError, SummaryEntry, SummaryRequest, SummaryResult

# Per model: context window (tokens), neurons per million input / output tokens,
# the output-length parameter name and its value.
# Sources (read 2026-11-20): model pages + developers.cloudflare.com/workers-ai/platform/pricing/
MODELS: dict[str, dict] = {
    # Default. Reasoning model: its reasoning counts as output tokens, so it gets a
    # larger output budget. `max_tokens` is deprecated for it in favour of
    # `max_completion_tokens`.
    "@cf/zai-org/glm-4.7-flash": {"context": 131_072, "in": 5_500, "out": 36_400,
                                  "max_param": "max_completion_tokens", "max_out": 2_048},
    # Deprecated by Cloudflare on 2026-05-30 (changelog 2026-05-08); kept for old configs.
    "@cf/meta/llama-3.1-8b-instruct": {"context": 7_968, "in": 25_608, "out": 75_147},
    # Model page: planned deprecation 2026-11-20.
    "@cf/meta/llama-3.1-8b-instruct-fp8": {"context": 32_000, "in": 13_778, "out": 26_128},
}
DEFAULT_MODEL = "@cf/zai-org/glm-4.7-flash"
DEFAULT_CONTEXT = 7_968  # conservative for models not in the table

SYSTEM_PROMPT = (
    "You summarize the earlier steps of an AI coding agent so it can continue its task. "
    "Write only bullet lines that start with '- '. Each line states one fact that appears in the "
    "tool outputs: a command and what it showed, a file and what it contains, an error, or a result. "
    "Quote file names, numbers and error messages exactly. Do not guess and do not add anything "
    "that is not in the tool outputs. At most 25 lines."
)


class CloudflareSummarizer:
    name = "cloudflare"

    def __init__(self, account_id: str, api_token: str, model: str = DEFAULT_MODEL,
                 max_output_tokens: int | None = None, timeout_s: float = 60.0, client: httpx.AsyncClient | None = None):
        if not account_id or not api_token:
            raise SummarizerError("CF_ACCOUNT_ID and CF_API_TOKEN must be set")
        self.account_id = account_id
        self._token = api_token
        self.model = model
        spec = MODELS.get(model, {})
        self.max_param = spec.get("max_param", "max_tokens")
        self.max_output_tokens = max_output_tokens or int(spec.get("max_out", 512))
        self.timeout_s = timeout_s
        self._client = client
        self.context = int(spec.get("context", DEFAULT_CONTEXT))
        self._neurons = (spec.get("in"), spec.get("out"))

    def __repr__(self) -> str:
        return f"CloudflareSummarizer(model={self.model!r})"

    @classmethod
    def from_config(cls, config) -> "CloudflareSummarizer":
        return cls(config.cf_account_id or "", config.cf_api_token or "", config.cf_model)

    @property
    def url(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{self.model}"

    def neurons(self, in_tokens: int, out_tokens: int) -> float:
        n_in, n_out = self._neurons
        if n_in is None:
            return 0.0
        return round(in_tokens * n_in / 1e6 + out_tokens * n_out / 1e6, 2)

    def split(self, request: SummaryRequest) -> list[list[SummaryEntry]]:
        """Split entries so each part (prompt + entries) fits the model's context."""
        overhead = count_tokens(SYSTEM_PROMPT) + count_tokens(request.task[:2000]) + 100
        room = max(500, int((self.context - self.max_output_tokens - overhead) * 0.9))
        parts: list[list[SummaryEntry]] = [[]]
        used = 0
        for e in request.entries:
            t = count_tokens(e.text) + count_tokens(e.heading) + 8
            if t > room:  # one huge entry: keep its head
                from ..tokens import clip_to_tokens

                e = SummaryEntry(e.heading, clip_to_tokens(e.text, room - 50))
                t = room
            if parts[-1] and used + t > room:
                parts.append([])
                used = 0
            parts[-1].append(e)
            used += t
        return [p for p in parts if p]

    @staticmethod
    def _user_prompt(task: str, entries: list[SummaryEntry]) -> str:
        body = "\n\n".join(f"### {e.heading}\n{e.text}" for e in entries)
        return f"Task of the agent:\n{task[:2000]}\n\nEarlier steps to summarize:\n\n{body}"

    async def _run(self, client: httpx.AsyncClient, messages: list[dict]) -> tuple[str, int, int]:
        body = {"messages": messages, self.max_param: self.max_output_tokens, "temperature": 0.2}
        try:
            resp = await client.post(self.url, json=body, headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as exc:
            raise SummarizerError(f"Could not reach Cloudflare Workers AI: {type(exc).__name__}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise SummarizerError(f"Cloudflare returned HTTP {resp.status_code} (not JSON)") from exc
        if resp.status_code != 200 or not data.get("success", False):
            errs = "; ".join(str(e.get("message", e)) for e in data.get("errors") or []) or resp.text[:200]
            raise SummarizerError(f"Cloudflare returned HTTP {resp.status_code}: {errs}")
        result = data.get("result") or {}
        if isinstance(result.get("response"), str):
            text = result["response"]
        else:
            try:
                text = result["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise SummarizerError("Unexpected Cloudflare response shape") from exc
        text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
        if not text:
            raise SummarizerError("Cloudflare returned an empty summary (output budget used up by reasoning?)")
        usage = result.get("usage") or {}
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        texts, tin, tout = [], 0, 0
        try:
            for part in self.split(request):
                messages = [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": self._user_prompt(request.task, part)}]
                text, i, o = await self._run(client, messages)
                if not i:
                    i = sum(count_tokens(m["content"]) for m in messages)
                if not o:
                    o = count_tokens(text)
                texts.append(text.strip())
                tin, tout = tin + i, tout + o
        finally:
            if self._client is None:
                await client.aclose()
        return SummaryResult("\n".join(texts), self.neurons(tin, tout), False, tin)

    async def test_connection(self) -> bool:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            await self._run(client, [{"role": "user", "content": "Reply with OK."}])
        finally:
            if self._client is None:
                await client.aclose()
        return True
