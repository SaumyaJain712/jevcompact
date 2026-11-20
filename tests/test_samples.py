"""Sample data checks (section 9). No judge is run here."""
import json
from pathlib import Path

import pytest

from jevcompact import parse_session
from jevcompact.formats import total_tokens

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
NAMES = sorted(p.stem for p in SAMPLES.glob("*.json") if not p.name.endswith(".labels.json"))


def test_required_samples_exist():
    assert len(NAMES) >= 6
    for n in ["checkout-bugfix-0412", "api-refactor-long", "data-pipeline-test", "docs-migration"]:
        assert n in NAMES
    formats = {parse_session(json.loads((SAMPLES / f"{n}.json").read_text())).format for n in NAMES}
    assert formats == {"openai", "anthropic"}


@pytest.mark.parametrize("name", NAMES)
def test_labels_cover_every_tool_result(name):
    msgs = json.loads((SAMPLES / f"{name}.json").read_text())
    labels = json.loads((SAMPLES / f"{name}.labels.json").read_text())
    s = parse_session(msgs)
    tool_ids = [it.tool_call_id for it in s.items if it.role in ("TOOL", "ERROR")]
    assert tool_ids == [i["tool_call_id"] for i in labels["items"]]
    assert all(i["reason"] for i in labels["items"]) and any(i["needed"] for i in labels["items"])
    over = total_tokens(msgs) > 120_000
    assert over == (name != "docs-migration")


def test_checkout_contains_spec_details():
    text = (SAMPLES / "checkout-bugfix-0412.json").read_text()
    for needle in ["TypeError: total is undefined (cart.ts:88)", "ls -la node_modules", "grep -rn price", "npm test"]:
        assert needle in text
