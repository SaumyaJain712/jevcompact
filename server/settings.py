"""Settings: thresholds, budget, toggles and encrypted provider keys."""
from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from jevcompact.config import PRESETS, THRESHOLD_ERROR, CompactionConfig

from .crypto import SecretBox, mask
from .db import Database

DEFAULTS = {
    "budget": 120_000,
    "keep_threshold": 0.50,
    "drop_threshold": 0.10,
    "preset": "balanced",
    "fallback_enabled": True,
    "never_drop_errors": True,
}
SECRET_KEYS = ("jev_api_key", "cf_api_token")
PLAIN_KEYS = ("cf_account_id",)


class SettingsIn(BaseModel):
    budget: int = Field(DEFAULTS["budget"], gt=0)
    keep_threshold: float = Field(DEFAULTS["keep_threshold"], ge=0, le=1)
    drop_threshold: float = Field(DEFAULTS["drop_threshold"], ge=0, le=1)
    preset: Literal["conservative", "balanced", "aggressive", "custom"] = "balanced"
    fallback_enabled: bool = True
    never_drop_errors: Literal[True] = True  # locked on
    # None = leave unchanged, "" = clear
    jev_api_key: str | None = None
    cf_account_id: str | None = None
    cf_api_token: str | None = None

    @model_validator(mode="after")
    def _thresholds(self):
        if self.keep_threshold <= self.drop_threshold:
            raise ValueError(THRESHOLD_ERROR)
        return self


class RunParams(BaseModel):
    preset: Literal["conservative", "balanced", "aggressive", "custom"] | None = None
    keep_threshold: float | None = Field(None, ge=0, le=1)
    drop_threshold: float | None = Field(None, ge=0, le=1)
    budget: int | None = Field(None, gt=0)
    keep_when_unsure: bool | None = None


class SettingsStore:
    def __init__(self, db: Database, box: SecretBox):
        self.db = db
        self.box = box

    def _values(self) -> dict:
        vals = dict(DEFAULTS)
        for k, (v, enc) in self.db.setting_rows().items():
            if not enc and k in DEFAULTS:
                vals[k] = json.loads(v)
        return vals

    def secret(self, key: str) -> str | None:
        row = self.db.setting_rows().get(key)
        if not row:
            return None
        value, enc = row
        return self.box.decrypt(value) if enc else value

    def public(self) -> dict:
        """Settings for the UI. Keys are masked, never returned in full."""
        out = self._values()
        for k in SECRET_KEYS:
            out[f"{k}_set"] = bool(self.secret(k))
            out[f"{k}_masked"] = mask(self.secret(k))
        out["cf_account_id"] = self.secret("cf_account_id") or ""
        out["judge"], out["summarizer"] = self.providers()
        return out

    def save(self, s: SettingsIn) -> dict:
        for k in DEFAULTS:
            self.db.set_setting(k, json.dumps(getattr(s, k)))
        for k in SECRET_KEYS + PLAIN_KEYS:
            v = getattr(s, k)
            if v is None:
                continue
            if v == "":
                self.db.delete_setting(k)
            elif k in SECRET_KEYS:
                self.db.set_setting(k, self.box.encrypt(v.strip()), encrypted=True)
            else:
                self.db.set_setting(k, v.strip())
        return self.public()

    def reset(self) -> dict:
        """Reset thresholds, budget and toggles. Saved keys are kept."""
        for k in DEFAULTS:
            self.db.delete_setting(k)
        return self.public()

    def providers(self) -> tuple[str, str]:
        """JUDGE / SUMMARIZER env vars win; otherwise use a real provider when its keys are saved.

        Judge: Jev when a Jev key is saved, else the free Cloudflare judge (standing in for Jev)
        when Cloudflare keys are saved, else the mock."""
        has_jev = bool(self.secret("jev_api_key") or os.environ.get("JEV_API_KEY"))
        has_cf = bool((self.secret("cf_account_id") or os.environ.get("CF_ACCOUNT_ID"))
                      and (self.secret("cf_api_token") or os.environ.get("CF_API_TOKEN")))
        judge = os.environ.get("JUDGE") or ("jev" if has_jev else "cloudflare" if has_cf else "mock")
        summ = os.environ.get("SUMMARIZER") or ("cloudflare" if has_cf else "mock")
        return judge, summ

    def build_config(self, params: RunParams | None = None) -> CompactionConfig:
        vals = self._values()
        p = params or RunParams()
        preset = p.preset or vals["preset"]
        keep = p.keep_threshold if p.keep_threshold is not None else vals["keep_threshold"]
        drop = p.drop_threshold if p.drop_threshold is not None else vals["drop_threshold"]
        if p.preset and p.preset != "custom" and p.keep_threshold is None and p.drop_threshold is None:
            keep, drop = PRESETS[p.preset]
        judge, summ = self.providers()
        overrides = {
            "budget": p.budget or vals["budget"], "preset": preset, "keep_threshold": keep, "drop_threshold": drop,
            "fallback_enabled": vals["fallback_enabled"], "judge": judge, "summarizer": summ,
        }
        if p.keep_when_unsure is not None:
            overrides["keep_when_unsure"] = p.keep_when_unsure
        for k in SECRET_KEYS + PLAIN_KEYS:
            if self.secret(k):
                overrides[k] = self.secret(k)
        return CompactionConfig.from_env(**overrides)
