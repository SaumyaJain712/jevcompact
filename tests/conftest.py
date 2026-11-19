import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from jevcompact import CompactionConfig, MemoryRecallStore, MockJudge, MockSummarizer  # noqa: E402


@pytest.fixture
def store():
    return MemoryRecallStore()


@pytest.fixture
def judge():
    return MockJudge()


@pytest.fixture
def summarizer():
    return MockSummarizer()


@pytest.fixture
def cfg():
    """Small budget so the small factory sessions are over budget."""
    return CompactionConfig(budget=3000)


def const_judge(value: float, **kw) -> MockJudge:
    return MockJudge(score_fn=lambda q, s: value, **kw)
