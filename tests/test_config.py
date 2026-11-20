"""Settings validation and provider wiring."""
import pytest
from pydantic import ValidationError

from jevcompact import CompactionConfig
from jevcompact.config import THRESHOLD_ERROR
from jevcompact.summarizers import CachingSummarizer, MockSummarizer, SummaryEntry, SummaryRequest


@pytest.mark.parametrize("keep,drop", [(0.1, 0.5), (0.3, 0.3)])
def test_keep_must_be_higher_than_drop(keep, drop):
    with pytest.raises(ValidationError) as e:
        CompactionConfig(keep_threshold=keep, drop_threshold=drop)
    assert THRESHOLD_ERROR in str(e.value)


@pytest.mark.parametrize("field,value", [("keep_threshold", 1.5), ("drop_threshold", -0.1), ("budget", 0)])
def test_out_of_range(field, value):
    with pytest.raises(ValidationError):
        CompactionConfig(**{field: value})


def test_never_drop_errors_is_locked_on():
    with pytest.raises(ValidationError):
        CompactionConfig(pin_errors=False)


def test_custom_thresholds_mark_preset_custom():
    c = CompactionConfig(keep_threshold=0.6, drop_threshold=0.15)
    assert c.preset == "custom"


def test_from_env(monkeypatch):
    monkeypatch.setenv("JUDGE", "mock")
    monkeypatch.setenv("SUMMARIZER", "mock")
    monkeypatch.setenv("JEV_API_KEY", "secret-key")
    c = CompactionConfig.from_env()
    assert c.judge == "mock" and c.jev_api_key == "secret-key"
    assert "secret-key" not in repr(c)
    assert "jev_api_key" not in c.public_dict()


def test_defaults_from_spec():
    c = CompactionConfig()
    assert (c.budget, c.keep_threshold, c.drop_threshold, c.check_threshold, c.min_savings) == \
        (120_000, 0.5, 0.1, 0.5, 0.10)
    assert (c.jev_max_request_tokens, c.jev_requests_per_s, c.jev_tokens_per_s) == (32_000, 80, 100_000)
    assert c.cut_chars == 400 and c.cf_model == "@cf/zai-org/glm-4.7-flash"


async def test_summary_cache_by_content_hash(tmp_path):
    inner = MockSummarizer()
    cache = CachingSummarizer(inner, tmp_path)
    req = SummaryRequest("task", [SummaryEntry("cat a.ts", "hello")])
    a = await cache.summarize(req)
    b = await cache.summarize(req)
    assert inner.calls == 1 and not a.cached and b.cached and a.text == b.text
    cache2 = CachingSummarizer(MockSummarizer(), tmp_path)  # disk cache survives restarts
    assert (await cache2.summarize(req)).cached


def test_mock_latency_env(monkeypatch):
    from jevcompact.judges import build_judge

    monkeypatch.setenv("MOCK_JUDGE_LATENCY_MS", "70,500")
    assert build_judge(CompactionConfig()).latency_ms == (70.0, 500.0)
    monkeypatch.setenv("MOCK_JUDGE_LATENCY_MS", "6000")
    assert build_judge(CompactionConfig()).latency_ms == (6000.0, 6000.0)
    monkeypatch.delenv("MOCK_JUDGE_LATENCY_MS")
    assert build_judge(CompactionConfig()).latency_ms == (0.0, 0.0)
