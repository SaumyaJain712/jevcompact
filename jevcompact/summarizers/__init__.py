from .base import (CachingSummarizer, Summarizer, SummarizerError, SummaryEntry, SummaryRequest,
                   SummaryResult)
from .mock import MockSummarizer

__all__ = ["Summarizer", "SummarizerError", "SummaryEntry", "SummaryRequest", "SummaryResult",
           "CachingSummarizer", "MockSummarizer", "build_summarizer"]


def build_summarizer(config, cache_dir=None) -> Summarizer:
    if config.summarizer == "cloudflare":
        from .cloudflare import CloudflareSummarizer  # added in phase (b)

        return CachingSummarizer(CloudflareSummarizer.from_config(config), cache_dir)
    return CachingSummarizer(MockSummarizer(), cache_dir)
