"""Configuration for a compaction run.

Jev limits (32k tokens of state + questions per request, 80 requests/s,
100k tokens/s, English only, $0.042 per million input tokens) come from our
SRS, which cites TypeSafe's models page (Oct 2026). TypeSafe's quickstart does
not state them, so they are kept here as configurable defaults.
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PRESETS: dict[str, tuple[float, float]] = {
    "conservative": (0.30, 0.05),
    "balanced": (0.50, 0.10),
    "aggressive": (0.70, 0.20),
}

THRESHOLD_ERROR = "Keep threshold must be higher than drop threshold."


class CompactionConfig(BaseModel):
    # Budget / trigger
    budget: int = Field(120_000, gt=0, description="Token budget; compaction starts above it.")

    # Thresholds (applied directly to Jev's noul value)
    preset: Literal["conservative", "balanced", "aggressive", "custom"] = "balanced"
    keep_threshold: float = Field(0.50, ge=0.0, le=1.0)
    drop_threshold: float = Field(0.10, ge=0.0, le=1.0)
    keep_when_unsure: bool = False
    cut_lines: int = Field(10, ge=1)
    cut_chars: int = Field(400, ge=50)

    # Pinning
    pin_last_turns: int = Field(1, ge=1)
    pin_errors: Literal[True] = True  # "Never drop error output (always on)"

    # Summary + check
    check_threshold: float = Field(0.5, ge=0.0, le=1.0)
    summary_reserve_tokens: int = Field(1_500, ge=0)

    # Fallback
    fallback_enabled: bool = True
    min_savings: float = Field(0.10, ge=0.0, le=1.0)

    # Jev limits (from SRS, see module docstring)
    jev_max_request_tokens: int = Field(32_000, gt=1000)
    jev_requests_per_s: float = Field(80, gt=0)
    jev_tokens_per_s: float = Field(100_000, gt=0)
    jev_timeout_s: float = Field(5.0, gt=0)
    jev_price_per_m_input: float = 0.042
    # Each tool output is clipped to this many tokens (head + tail) inside the
    # Jev state, so a 180k-token session costs about $0.001 to score.
    jev_item_max_tokens: int = Field(300, ge=50)
    # Total source tokens shown to Jev when checking summary lines.
    check_source_max_tokens: int = Field(12_000, ge=500)

    # Providers
    judge: Literal["jev", "mock"] = "mock"
    summarizer: Literal["cloudflare", "mock"] = "mock"
    jev_api_key: str | None = Field(None, repr=False)
    jev_base_url: str = "https://api.typesafe.ai/v1"
    jev_model: str = "jev-latest"
    cf_account_id: str | None = Field(None, repr=False)
    cf_api_token: str | None = Field(None, repr=False)
    cf_model: str = "@cf/meta/llama-3.1-8b-instruct"

    @model_validator(mode="after")
    def _apply_preset_and_validate(self) -> "CompactionConfig":
        explicit = {"keep_threshold", "drop_threshold"} & self.model_fields_set
        if self.preset != "custom" and not explicit:
            self.keep_threshold, self.drop_threshold = PRESETS[self.preset]
        elif explicit and "preset" not in self.model_fields_set:
            if (self.keep_threshold, self.drop_threshold) not in PRESETS.values():
                self.preset = "custom"
        if self.keep_threshold <= self.drop_threshold:
            raise ValueError(THRESHOLD_ERROR)
        return self

    @classmethod
    def from_preset(cls, name: str, **overrides) -> "CompactionConfig":
        keep, drop = PRESETS[name]
        return cls(preset=name, keep_threshold=keep, drop_threshold=drop, **overrides)

    @classmethod
    def from_env(cls, **overrides) -> "CompactionConfig":
        env = os.environ
        values: dict = {
            "judge": env.get("JUDGE", "mock"),
            "summarizer": env.get("SUMMARIZER", "mock"),
            "jev_api_key": env.get("JEV_API_KEY") or None,
            "cf_account_id": env.get("CF_ACCOUNT_ID") or None,
            "cf_api_token": env.get("CF_API_TOKEN") or None,
        }
        if env.get("JEV_BASE_URL"):
            values["jev_base_url"] = env["JEV_BASE_URL"]
        if env.get("CF_MODEL"):
            values["cf_model"] = env["CF_MODEL"]
        values.update(overrides)
        return cls(**values)

    def public_dict(self) -> dict:
        """Config without secrets, safe to log or store with a run."""
        return self.model_dump(exclude={"jev_api_key", "cf_api_token", "cf_account_id"})
