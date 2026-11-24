import os

from .base import Judge, JudgeError, JudgeResponse, Question
from .mock import MockJudge

__all__ = ["Judge", "JudgeError", "JudgeResponse", "Question", "MockJudge", "build_judge"]


def build_judge(config) -> Judge:
    if config.judge == "jev":
        from .jev import JevJudge  # added in phase (b)

        return JevJudge.from_config(config)
    if config.judge == "cloudflare":
        from .cloudflare import CloudflareJudge

        return CloudflareJudge.from_config(config)
    return MockJudge(latency_ms=mock_latency_from_env())


def mock_latency_from_env() -> tuple[float, float]:
    """MOCK_JUDGE_LATENCY_MS="70,500" (uniform range) or "6000" makes MockJudge as slow as asked.

    Used to simulate Jev's 70-500 ms latency and, in UI tests, a real 5 s timeout.
    """
    raw = os.environ.get("MOCK_JUDGE_LATENCY_MS", "").strip()
    if not raw:
        return (0.0, 0.0)
    parts = [float(x) for x in raw.split(",")]
    return (parts[0], parts[-1])
