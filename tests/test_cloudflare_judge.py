"""CloudflareJudge (the free stand-in for Jev) against mocked HTTP (respx). No network, no neurons spent."""
import json

import httpx
import pytest
import respx
from factories import Step, build, filler

from jevcompact import CompactionConfig, MockSummarizer, compact
from jevcompact.batching import effective_cap
from jevcompact.judges import JudgeError, build_judge
from jevcompact.judges.base import Question
from jevcompact.judges.cloudflare import CloudflareJudge, InvalidJudgeReply, judge_label, parse_scores
from jevcompact.recall import MemoryRecallStore

GRANITE = "@cf/ibm-granite/granite-4.0-h-micro"
GLM = "@cf/zai-org/glm-4.7-flash"
URL = f"https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/{GRANITE}"
GLM_URL = f"https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/{GLM}"
Q = [Question("t1", "keep", "Is tool output [t1] still needed to finish the task?", meta={"title": "cat a.ts"}),
     Question("t2", "keep", "Is tool output [t2] still needed to finish the task?")]


def reply(scores, *, chat=False, neurons=1.5, raw=None):
    """Workers AI shape (`result.response`, already parsed in JSON mode) or chat-completion shape."""
    content = raw if raw is not None else {"scores": scores}
    usage = {"prompt_tokens": 1000, "completion_tokens": 20, "neurons": neurons}
    if chat:
        text = content if isinstance(content, str) else json.dumps(content)
        result = {"choices": [{"message": {"content": text}}], "usage": usage}
    else:
        result = {"response": content, "usage": usage}
    return httpx.Response(200, json={"success": True, "errors": [], "result": result})


def judge(**kw):
    return CloudflareJudge("acc123", "tok", GRANITE, **kw)


@respx.mock
async def test_request_shape_temperature_zero_and_json_schema():
    route = respx.post(URL).mock(return_value=reply({"t1": 0.9, "t2": 0.05}))
    res = await judge().evaluate("STATE", Q)
    sent = json.loads(route.calls[0].request.content)
    assert sent["temperature"] == 0
    assert route.calls[0].request.headers["authorization"] == "Bearer tok"
    user = sent["messages"][1]["content"]
    # Exactly Jev's yes/no question, with the item title beside the id when known.
    assert "t1 (cat a.ts): Is tool output [t1] still needed to finish the task?" in user
    assert "t2: Is tool output [t2] still needed to finish the task?" in user
    schema = sent["response_format"]["json_schema"]
    assert schema["properties"]["scores"]["required"] == ["t1", "t2"]
    assert res.scores == {"t1": 0.9, "t2": 0.05}
    assert res.neurons == 1.5 and res.attempts == 1 and res.input_tokens == 1000


@respx.mock
async def test_glm_chat_shape_reasoning_on_no_schema():
    route = respx.post(GLM_URL).mock(return_value=reply({"t1": 1, "t2": 0}, chat=True))
    res = await CloudflareJudge("acc123", "tok", GLM).evaluate("STATE", Q)
    sent = json.loads(route.calls[0].request.content)
    assert "response_format" not in sent and "chat_template_kwargs" not in sent  # reasoning stays on
    assert sent["max_completion_tokens"] >= 4000
    assert res.scores == {"t1": 1.0, "t2": 0.0}


@respx.mock
async def test_invalid_json_is_retried_once():
    route = respx.post(URL).mock(side_effect=[reply(None, raw="Sure! t1 is needed."),
                                              reply({"t1": 0.7, "t2": 0.2}, neurons=2.0)])
    res = await judge().evaluate("STATE", Q)
    assert route.call_count == 2
    assert res.attempts == 2 and res.scores["t1"] == 0.7
    assert res.neurons == 3.5  # both calls are billed


@respx.mock
async def test_invalid_twice_is_judge_error_with_neurons():
    respx.post(URL).mock(side_effect=[reply(None, raw="nope"), reply({"t1": 0.5})])  # 2nd misses t2
    with pytest.raises(JudgeError, match="invalid JSON twice") as e:
        await judge().evaluate("STATE", Q)
    assert e.value.neurons == 3.0


@pytest.mark.parametrize("raw, msg", [
    ("not json", "not JSON"),
    ([0.1, 0.2], "JSON object"),
    ({"t1": 0.1, "t2": 0.2}, '"scores"'),
    ({"scores": {"t1": 0.1}}, "t2"),
    ({"scores": {"t1": 1.2, "t2": 0}}, "t1"),
    ({"scores": {"t1": "0.4", "t2": 0}}, "t1"),
    ({"scores": {"t1": True, "t2": 0}}, "t1"),
])
def test_parse_scores_is_strict(raw, msg):
    with pytest.raises(InvalidJudgeReply, match=msg):
        parse_scores(raw if not isinstance(raw, str) else raw, ["t1", "t2"])


def test_parse_scores_accepts_code_fence_and_think_block():
    assert parse_scores('<think>hmm</think>```json\n{"scores": {"t1": 0, "t2": 1}}\n```', ["t1", "t2"]) == \
        {"t1": 0.0, "t2": 1.0}


@respx.mock
async def test_http_error_retried_then_raised():
    respx.post(URL).mock(side_effect=[httpx.Response(503, json={"success": False, "errors": [{"message": "busy"}]}),
                                      httpx.Response(401, json={"success": False, "errors": [{"message": "bad token"}]})])
    with pytest.raises(JudgeError, match="401: bad token"):
        await judge().evaluate("STATE", Q)


def session():
    return build([Step(f"cat src/f{i}.ts", filler(900, f"f{i}")) for i in range(30)])


@respx.mock
async def test_invalid_json_twice_falls_back_like_a_jev_failure():
    respx.post(URL).mock(return_value=reply(None, raw="I cannot answer that."))
    res = await compact(session(), CompactionConfig(budget=6_000), judge=judge(), summarizer=MockSummarizer(),
                        recall_store=MemoryRecallStore())
    assert res.status == "Fell back"
    assert "invalid JSON twice" in res.fallback_reason
    assert res.user_messages_lost == 0


@respx.mock
async def test_pipeline_uses_judge_cap_reports_neurons_not_dollars():
    def answer(request):
        body = json.loads(request.content)
        ids = body["response_format"]["json_schema"]["properties"]["scores"]["required"]
        return reply({i: 0.05 for i in ids}, neurons=4.0)

    route = respx.post(URL).mock(side_effect=answer)
    j = judge(max_request_tokens=4_000)
    cfg = CompactionConfig(budget=6_000, jev_item_max_tokens=1_000)
    res = await compact(session(), cfg, judge=j, summarizer=MockSummarizer(), recall_store=MemoryRecallStore())
    assert res.status == "Compacted"
    assert route.call_count == res.jev_requests >= 2  # 4k-token requests instead of Jev's 32k
    for call in route.calls:
        from jevcompact.tokens import count_tokens

        assert count_tokens(json.loads(call.request.content)["messages"][1]["content"]) < 4_000 + 400
    assert res.judge_neurons == pytest.approx(4.0 * route.call_count)
    assert res.jev_cost_usd == 0.0


def test_judge_selectable_from_config_and_env(monkeypatch):
    cfg = CompactionConfig(judge="cloudflare", cf_account_id="acc123", cf_api_token="tok")
    j = build_judge(cfg)
    assert isinstance(j, CloudflareJudge) and j.model == GRANITE
    assert j.max_request_tokens == 16_000 and j.request_timeout_s > cfg.jev_timeout_s
    monkeypatch.setenv("JUDGE", "cloudflare")
    monkeypatch.setenv("CF_JUDGE_MODEL", GLM)
    env = CompactionConfig.from_env()
    assert env.judge == "cloudflare" and env.cf_judge_model == GLM
    with pytest.raises(ValueError):
        CompactionConfig(judge="openai")


def test_requires_credentials_and_hides_token():
    with pytest.raises(JudgeError, match="CF_ACCOUNT_ID"):
        CloudflareJudge("", "tok")
    assert "tok" not in repr(judge())


def test_label_names_the_model_family():
    assert judge_label(GRANITE) == "Cloudflare (Granite) judge, standing in for Jev"
    assert judge_label(GLM) == "Cloudflare (GLM) judge, standing in for Jev"


def test_effective_cap_under_judge_cap():
    assert effective_cap(judge().max_request_tokens) < 16_000
