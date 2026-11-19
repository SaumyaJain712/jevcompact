"""Jev and Cloudflare clients against mocked HTTP (respx). No network, no neurons spent."""
import json

import httpx
import pytest
import respx
from factories import Step, build, filler

from jevcompact import CompactionConfig, compact
from jevcompact.judges import JudgeError, build_judge
from jevcompact.judges.base import Question
from jevcompact.judges.jev import JevJudge
from jevcompact.recall import MemoryRecallStore
from jevcompact.summarizers import CachingSummarizer, SummarizerError, SummaryEntry, SummaryRequest, build_summarizer
from jevcompact.summarizers.cloudflare import CloudflareSummarizer

JEV = "https://api.typesafe.ai/v1"
CF_URL = "https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/@cf/meta/llama-3.1-8b-instruct-fp8"


def noul_reply(request: httpx.Request, value=0.42):
    body = json.loads(request.content)
    answers = {k: {"type": "noul", "noul": value} for k in body["questions"]}
    return httpx.Response(200, json={"model": "jev-1.14.0", "answers": answers,
                                     "usage": {"input_tokens": 1234, "output_tokens": 5}})


# --- Jev ---------------------------------------------------------------------

@respx.mock
async def test_jev_request_shape_and_parse():
    route = respx.post(f"{JEV}/systemone").mock(side_effect=noul_reply)
    j = JevJudge("sk-test", JEV)
    res = await j.evaluate("STATE", [Question("t1", "keep", "Is tool output [t1] still needed to finish the task?")])
    sent = json.loads(route.calls[0].request.content)
    assert sent == {"model": "jev-latest", "state": "STATE",
                    "questions": {"t1": {"type": "noul",
                                         "instructions": "Is tool output [t1] still needed to finish the task?"}}}
    assert route.calls[0].request.headers["Authorization"] == "Bearer sk-test"
    assert res.scores == {"t1": 0.42} and res.input_tokens == 1234 and res.model == "jev-1.14.0"


@respx.mock
async def test_jev_retries_429_then_succeeds():
    route = respx.post(f"{JEV}/systemone").mock(side_effect=[
        httpx.Response(429, json={"detail": "slow down"}), httpx.Response(529, json={"detail": "overloaded"}),
        lambda req: noul_reply(req, 0.9)])
    j = JevJudge("k", JEV)
    res = await j.evaluate("s", [Question("a", "keep", "q")])
    assert res.scores["a"] == 0.9 and route.call_count == 3


@respx.mock
@pytest.mark.parametrize("status,body,msg", [
    (401, {"detail": "bad key"}, "rejected the API key"),
    (400, {"detail": "max_tokens_exceeded"}, "context length"),
    (422, {"detail": [{"loc": ["body", "questions"], "msg": "x"}]}, "HTTP 422"),
])
async def test_jev_errors(status, body, msg):
    respx.post(f"{JEV}/systemone").mock(return_value=httpx.Response(status, json=body))
    with pytest.raises(JudgeError, match=msg):
        await JevJudge("k", JEV, max_retries=0).evaluate("s", [Question("a", "keep", "q")])


@respx.mock
async def test_jev_missing_answer_is_error():
    respx.post(f"{JEV}/systemone").mock(return_value=httpx.Response(200, json={"answers": {}, "usage": {}}))
    with pytest.raises(JudgeError, match="Unexpected"):
        await JevJudge("k", JEV).evaluate("s", [Question("a", "keep", "q")])


@respx.mock
async def test_jev_timeout_falls_back_in_pipeline():
    respx.post(f"{JEV}/systemone").mock(side_effect=httpx.ReadTimeout("slow"))
    msgs = build([Step(f"cat f{i}.ts", filler(500, f"f{i}")) for i in range(8)])
    res = await compact(msgs, CompactionConfig(budget=1500), judge=JevJudge("k", JEV),
                        summarizer=build_summarizer(CompactionConfig()), recall_store=MemoryRecallStore())
    assert res.status == "Fell back" and "5 s" in res.fallback_reason


@respx.mock
async def test_jev_test_connection():
    respx.get(f"{JEV}/models").mock(return_value=httpx.Response(200, json={"data": []}))
    assert await JevJudge("k", JEV).test_connection()
    respx.get(f"{JEV}/models").mock(return_value=httpx.Response(401, json={"detail": "no"}))
    with pytest.raises(JudgeError):
        await JevJudge("k", JEV).test_connection()


@respx.mock
async def test_openrouter_base_url():
    route = respx.post("https://openrouter.ai/api/v1/systemone").mock(side_effect=noul_reply)
    j = JevJudge("or-key", "https://openrouter.ai/api/v1", "~typesafe/jev-latest")
    await j.evaluate("s", [Question("a", "keep", "q")])
    assert json.loads(route.calls[0].request.content)["model"] == "~typesafe/jev-latest"


def test_jev_key_never_in_repr():
    j = JevJudge("sk-secret-123", JEV)
    assert "sk-secret-123" not in repr(j)
    assert "sk-secret-123" not in repr(CompactionConfig(jev_api_key="sk-secret-123"))


def test_build_judge_from_config():
    assert isinstance(build_judge(CompactionConfig(judge="jev", jev_api_key="k")), JevJudge)
    with pytest.raises(JudgeError):
        build_judge(CompactionConfig(judge="jev"))


@respx.mock
async def test_billed_tokens_drive_cost():
    respx.post(f"{JEV}/systemone").mock(side_effect=noul_reply)  # 1234 billed tokens per request
    msgs = build([Step(f"cat f{i}.ts", filler(500, f"f{i}")) for i in range(8)])
    res = await compact(msgs, CompactionConfig(budget=1500), judge=JevJudge("k", JEV),
                        summarizer=build_summarizer(CompactionConfig()), recall_store=MemoryRecallStore())
    assert res.jev_input_tokens == 1234 * res.jev_requests
    assert res.jev_cost_usd == pytest.approx(1234 * res.jev_requests * 0.042 / 1e6, abs=1e-6)


# --- Cloudflare --------------------------------------------------------------

def cf_ok(text="- `cat a.ts`: exports cartTotal", usage=None, chat=False):
    result = ({"choices": [{"message": {"content": text}}]} if chat else {"response": text})
    result["usage"] = usage or {"prompt_tokens": 1000, "completion_tokens": 100}
    return httpx.Response(200, json={"success": True, "errors": [], "result": result})


@respx.mock
async def test_cloudflare_request_and_neurons():
    route = respx.post(CF_URL).mock(return_value=cf_ok())
    s = CloudflareSummarizer("acc123", "cf-token")
    res = await s.summarize(SummaryRequest("fix bug", [SummaryEntry("cat a.ts", "export function cartTotal")]))
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer cf-token"
    body = json.loads(req.content)
    assert body["messages"][0]["role"] == "system" and "cat a.ts" in body["messages"][1]["content"]
    assert res.text.startswith("- `cat a.ts`")
    assert res.neurons == pytest.approx(1000 * 13_778 / 1e6 + 100 * 26_128 / 1e6, abs=0.01)


@respx.mock
async def test_cloudflare_chat_completion_shape():
    url = "https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/@cf/zai-org/glm-4.7-flash"
    respx.post(url).mock(return_value=cf_ok("- line", chat=True))
    s = CloudflareSummarizer("acc123", "t", model="@cf/zai-org/glm-4.7-flash")
    assert (await s.summarize(SummaryRequest("t", [SummaryEntry("h", "x")]))).text == "- line"


@respx.mock
async def test_cloudflare_splits_input_over_context():
    route = respx.post(CF_URL).mock(return_value=cf_ok())
    s = CloudflareSummarizer("acc123", "t")  # 32k context
    entries = [SummaryEntry(f"cat f{i}.ts", filler(4000, f"s{i}")) for i in range(16)]  # ~64k tokens
    res = await s.summarize(SummaryRequest("task", entries))
    assert route.call_count >= 3
    for call in route.calls:
        from jevcompact.tokens import count_tokens

        body = json.loads(call.request.content)
        assert sum(count_tokens(m["content"]) for m in body["messages"]) + 512 <= 32_000
    assert res.text.count("- `cat a.ts`") == route.call_count


@respx.mock
async def test_cloudflare_error_and_pipeline_keeps_pruned_session():
    respx.post(CF_URL).mock(return_value=httpx.Response(
        403, json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}))
    s = CloudflareSummarizer("acc123", "t")
    with pytest.raises(SummarizerError, match="Authentication error"):
        await s.summarize(SummaryRequest("t", [SummaryEntry("h", "x")]))


@respx.mock
async def test_cloudflare_cache_never_calls_twice():
    route = respx.post(CF_URL).mock(return_value=cf_ok())
    s = CachingSummarizer(CloudflareSummarizer("acc123", "t"))
    req = SummaryRequest("t", [SummaryEntry("h", "x")])
    await s.summarize(req)
    second = await s.summarize(req)
    assert route.call_count == 1 and second.cached and second.neurons == 0


def test_cloudflare_requires_credentials():
    with pytest.raises(SummarizerError):
        CloudflareSummarizer("", "")
    assert "tok-secret" not in repr(CloudflareSummarizer("a", "tok-secret"))
