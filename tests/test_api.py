"""FastAPI server + SQLite: FR9 (DB log), FR10 data, FR11 re-run/restore/undo, FR12 export, settings, security."""
import json
import logging
import sqlite3
import time

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from factories import Step, build, checkout_session
from fastapi.testclient import TestClient

from jevcompact import MockJudge
from jevcompact.formats import UPLOAD_ERROR

SECRET = "sk-jev-super-secret-1234"
CF_TOKEN = "cf-token-very-secret-9876"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JUDGE", "mock")
    monkeypatch.setenv("SUMMARIZER", "mock")
    monkeypatch.setenv("JEVCOMPACT_SECRET_KEY", Fernet.generate_key().decode())
    for k in ("JEV_API_KEY", "CF_ACCOUNT_ID", "CF_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    from server.app import create_app

    app = create_app(tmp_path / "test.db", tmp_path)
    with TestClient(app) as c:
        r = c.put("/api/settings", json={"budget": 10000, "keep_threshold": 0.5, "drop_threshold": 0.1,
                                         "preset": "balanced", "fallback_enabled": True})
        assert r.status_code == 200, r.text
        c.db_path = tmp_path / "test.db"
        yield c


def upload(c, msgs=None, name="checkout-bugfix-0412", wait=True):
    r = c.post(f"/api/sessions?wait={str(wait).lower()}&name={name}", json=msgs or checkout_session())
    assert r.status_code == 201, r.text
    return r.json()


def wait_run(c, run_id, timeout=10):
    t = time.time()
    while time.time() - t < timeout:
        r = c.get(f"/api/runs/{run_id}").json()
        if r["status"] != "Running":
            return r
        time.sleep(0.05)
    raise AssertionError("run did not finish")


# --- sessions ----------------------------------------------------------------

def test_upload_runs_and_lists(client):
    s = upload(client)
    assert s["status"] == "Compacted" and s["tokens_after"] < s["tokens_before"]
    assert s["format"] == "openai" and s["message_count"] == len(checkout_session())
    upload(client, build([Step("ls", "a")]), name="docs-migration")
    rows = client.get("/api/sessions").json()
    assert {r["name"] for r in rows} == {"checkout-bugfix-0412", "docs-migration"}
    assert [r["name"] for r in client.get("/api/sessions?q=checkout").json()] == ["checkout-bugfix-0412"]
    assert [r["name"] for r in client.get("/api/sessions?status=Under budget").json()] == ["docs-migration"]
    assert [r["name"] for r in client.get("/api/sessions?status=Compacted").json()] == ["checkout-bugfix-0412"]


def test_upload_multipart_file(client):
    data = json.dumps(checkout_session("anthropic")).encode()
    r = client.post("/api/sessions?wait=true", files={"file": ("api-refactor-long.json", data, "application/json")})
    assert r.status_code == 201 and r.json()["name"] == "api-refactor-long" and r.json()["format"] == "anthropic"


@pytest.mark.parametrize("payload", [{"role": "user"}, [{"content": "x"}], [], "hello", [1, 2]])
def test_upload_validation_422(client, payload):
    r = client.post("/api/sessions", json=payload)
    assert r.status_code == 422 and r.json()["detail"] == UPLOAD_ERROR


def test_upload_rejects_non_json_file(client):
    r = client.post("/api/sessions", files={"file": ("notes.txt", b"[]", "text/plain")})
    assert r.status_code == 422 and r.json()["detail"] == UPLOAD_ERROR
    r = client.post("/api/sessions", files={"file": ("bad.json", b"{not json", "application/json")})
    assert r.status_code == 422 and r.json()["detail"] == UPLOAD_ERROR


def test_get_and_delete_session(client):
    s = upload(client)
    d = client.get(f"/api/sessions/{s['id']}").json()
    assert d["current_run"]["status"] == "Compacted" and d["current_run"]["percent_saved"] > 0
    assert set(d["current_run"]["counts"]) == {"Pinned", "Kept", "Cut", "Dropped"}
    assert client.delete(f"/api/sessions/{s['id']}").status_code == 204
    assert client.get(f"/api/sessions/{s['id']}").status_code == 404
    con = sqlite3.connect(client.db_path)
    assert con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0  # cascaded
    assert client.get("/api/sessions/nope").status_code == 404


# --- runs, decisions (FR9, FR10) -------------------------------------------------

def test_decisions_logged_in_db(client):
    s = upload(client)
    rows = client.get(f"/api/runs/{s['run_id']}/decisions").json()
    assert rows and all(r["action"] in ("Pinned", "Kept", "Cut", "Dropped") for r in rows)
    assert all(r["created_at"] and r["content"] is not None for r in rows)
    assert all(r["score"] is not None for r in rows if r["action"] != "Pinned")
    dropped = [r for r in rows if r["action"] == "Dropped"]
    assert dropped and all("Recall id" in r["content_after"] for r in dropped)
    con = sqlite3.connect(client.db_path)
    assert con.execute("SELECT COUNT(*) FROM decisions WHERE run_id = ?", (s["run_id"],)).fetchone()[0] == len(rows)


def test_rerun_with_thresholds_creates_new_version(client):
    s = upload(client)
    original = client.get(f"/api/sessions/{s['id']}/messages").json()
    r = client.post(f"/api/sessions/{s['id']}/runs?wait=true", json={"preset": "aggressive"}).json()
    assert r["keep_threshold"] == 0.7 and r["drop_threshold"] == 0.2 and r["preset"] == "aggressive"
    r2 = client.post(f"/api/sessions/{s['id']}/runs?wait=true",
                     json={"keep_threshold": 0.6, "drop_threshold": 0.3}).json()
    assert (r2["keep_threshold"], r2["drop_threshold"]) == (0.6, 0.3)
    assert len(client.get(f"/api/sessions/{s['id']}/runs").json()) == 3
    assert client.get(f"/api/sessions/{s['id']}").json()["current_run_id"] == r2["id"]
    assert client.get(f"/api/sessions/{s['id']}/messages").json() == original == checkout_session()


def test_rerun_rejects_bad_thresholds(client):
    s = upload(client)
    r = client.post(f"/api/sessions/{s['id']}/runs", json={"keep_threshold": 0.1, "drop_threshold": 0.4})
    assert r.status_code == 422 and "Keep threshold must be higher" in r.json()["detail"]


def test_background_run_and_cancel(client, monkeypatch):
    s = upload(client)
    r = client.post(f"/api/sessions/{s['id']}/runs", json={}).json()
    assert r["status"] == "Running"
    assert wait_run(client, r["id"])["status"] == "Compacted"

    import server.runner as runner

    monkeypatch.setattr(runner, "build_judge", lambda cfg: MockJudge(latency_ms=(3000, 3000)))
    r = client.post(f"/api/sessions/{s['id']}/runs", json={}).json()
    time.sleep(0.2)
    assert client.post(f"/api/runs/{r['id']}/cancel").json() == {"cancelled": True}
    assert wait_run(client, r["id"])["status"] == "Cancelled"
    assert client.post(f"/api/runs/{r['id']}/cancel").status_code == 409


def test_jev_failure_shows_fell_back(client, monkeypatch):
    import server.runner as runner

    monkeypatch.setattr(runner, "build_judge", lambda cfg: MockJudge(fail=True))
    s = upload(client)
    run = client.get(f"/api/runs/{s['run_id']}").json()
    assert run["status"] == "Fell back" and run["fallback_reason"]
    assert client.get("/api/sessions?status=Fell back").json()[0]["id"] == s["id"]


# --- restore, undo, redo (FR11) ---------------------------------------------------

def test_restore_returns_verbatim_and_undo_redo(client):
    s = upload(client)
    rows = client.get(f"/api/runs/{s['run_id']}/decisions").json()
    d = next(r for r in rows if r["action"] == "Dropped")
    assert client.get(f"/api/runs/{s['run_id']}/recall/{d['item_id']}").text == d["content"]

    new = client.post(f"/api/runs/{s['run_id']}/items/{d['item_id']}/restore")
    assert new.status_code == 201
    new = new.json()
    assert new["kind"] == "restore" and new["parent_run_id"] == s["run_id"]
    assert new["tokens_after"] > client.get(f"/api/runs/{s['run_id']}").json()["tokens_after"]
    after = next(r for r in client.get(f"/api/runs/{new['id']}/decisions").json() if r["item_id"] == d["item_id"])
    assert after["action"] == "Kept" and after["restored"] and after["content_after"] == d["content"]
    exported = client.get(f"/api/runs/{new['id']}/export.json").json()
    assert d["content"] in [m.get("content") for m in exported]

    sess = client.get(f"/api/sessions/{s['id']}").json()
    assert sess["current_run_id"] == new["id"] and sess["can_undo"] and not sess["can_redo"]
    assert client.post(f"/api/sessions/{s['id']}/undo").json()["current_run_id"] == s["run_id"]
    assert client.get(f"/api/sessions/{s['id']}").json()["can_redo"]
    assert client.post(f"/api/sessions/{s['id']}/redo").json()["current_run_id"] == new["id"]
    assert client.post(f"/api/sessions/{s['id']}/redo").status_code == 409

    # undo, then a new run discards the redo branch
    client.post(f"/api/sessions/{s['id']}/undo")
    client.post(f"/api/sessions/{s['id']}/runs?wait=true", json={})
    sess = client.get(f"/api/sessions/{s['id']}").json()
    assert not sess["can_redo"]
    assert [r["superseded"] for r in sess["runs"] if r["id"] == new["id"]] == [1]


def test_restore_rejects_pinned(client):
    s = upload(client)
    rows = client.get(f"/api/runs/{s['run_id']}/decisions").json()
    p = next(r for r in rows if r["action"] == "Pinned")
    assert client.post(f"/api/runs/{s['run_id']}/items/{p['item_id']}/restore").status_code == 409


# --- compare + export (FR10, FR12) ------------------------------------------------

def test_compare(client):
    s = upload(client)
    c = client.get(f"/api/runs/{s['run_id']}/compare").json()
    assert c["user_messages_touched"] == 0 and c["dropped"] >= 1
    before = [r["before"] for r in c["rows"] if r["before"]]
    assert [b["index"] for b in before] == list(range(len(checkout_session())))
    markers = {r["marker"] for r in c["rows"]}
    assert "Dropped" in markers
    dropped_row = next(r for r in c["rows"] if r["marker"] == "Dropped")
    assert dropped_row["after"]["tokens"] < dropped_row["before"]["tokens"]  # placeholder counted in after
    assert sum(r["after"]["tokens"] for r in c["rows"] if r["after"]) == c["tokens_after"]


def test_compare_with_summary(client):
    msgs = build([Step(f"cat src/m{i}.ts", "\n".join(f"line {j} of m{i}" for j in range(300))) for i in range(20)])
    s = upload(client, msgs, name="data-pipeline-test")
    r = client.post(f"/api/sessions/{s['id']}/runs?wait=true", json={"budget": 3000}).json()
    assert r["status"] == "Compacted" and r["summary"] is not None
    c = client.get(f"/api/runs/{r['id']}/compare").json()
    summary_rows = [x for x in c["rows"] if x["marker"] == "Summary"]
    assert len(summary_rows) == 1 and summary_rows[0]["before"] is None
    assert summary_rows[0]["after"]["text"].startswith("[JevCompact summary of")
    assert any(x["marker"] == "Summarized" and x["after"] is None for x in c["rows"])
    assert sum(r["after"]["tokens"] for r in c["rows"] if r["after"]) == c["tokens_after"]


def test_exports(client):
    s = upload(client)
    r = client.get(f"/api/runs/{s['run_id']}/export.json")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert isinstance(r.json(), list)
    csv_r = client.get(f"/api/runs/{s['run_id']}/report.csv")
    assert csv_r.headers["content-type"].startswith("text/csv")
    assert csv_r.text.splitlines()[0].startswith("item_id,message_index,role,title,score,action")
    rep = client.get(f"/api/runs/{s['run_id']}/report.json").json()
    assert rep["user_messages_touched"] == 0 and rep["decisions"]


# --- settings + security ---------------------------------------------------------

def test_settings_validation(client):
    r = client.put("/api/settings", json={"budget": 1000, "keep_threshold": 0.2, "drop_threshold": 0.3})
    assert r.status_code == 422 and r.json()["detail"] == "Keep threshold must be higher than drop threshold."
    assert client.put("/api/settings", json={"budget": 0}).status_code == 422
    assert client.put("/api/settings", json={"never_drop_errors": False}).status_code == 422
    assert client.get("/api/settings").json()["never_drop_errors"] is True


def test_settings_reset_keeps_keys(client):
    client.put("/api/settings", json={"budget": 5000, "keep_threshold": 0.6, "drop_threshold": 0.2,
                                      "jev_api_key": SECRET})
    s = client.post("/api/settings/reset").json()
    assert (s["budget"], s["keep_threshold"], s["drop_threshold"]) == (120000, 0.5, 0.1)
    assert s["jev_api_key_set"]


def test_keys_encrypted_masked_never_returned(client, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.put("/api/settings", json={"budget": 3000, "jev_api_key": SECRET, "cf_account_id": "acc1",
                                          "cf_api_token": CF_TOKEN})
    body = r.text
    s = r.json()
    assert s["jev_api_key_set"] and s["jev_api_key_masked"].endswith("1234") and s["jev_api_key_masked"].startswith("•")
    assert s["judge"] == "mock"  # JUDGE env wins in tests
    raw = sqlite3.connect(client.db_path).execute("SELECT value, encrypted FROM settings WHERE key='jev_api_key'").fetchone()
    assert raw[1] == 1 and SECRET not in raw[0]
    dump = "\n".join(sqlite3.connect(client.db_path).iterdump())
    assert SECRET not in dump and CF_TOKEN not in dump
    sess = upload(client)
    texts = [body, client.get("/api/settings").text, client.get(f"/api/sessions/{sess['id']}").text,
             client.get(f"/api/runs/{sess['run_id']}").text, client.get("/openapi.json").text]
    assert not any(SECRET in t or CF_TOKEN in t for t in texts)
    logging.getLogger("server").warning("debug value %s", SECRET)
    assert SECRET not in caplog.text and CF_TOKEN not in caplog.text


def test_clear_key(client):
    client.put("/api/settings", json={"jev_api_key": SECRET})
    assert client.put("/api/settings", json={"jev_api_key": ""}).json()["jev_api_key_set"] is False


@respx.mock
def test_connection_tests(client):
    respx.route(host="testserver").pass_through()
    assert client.post("/api/settings/test/jev", json={}).json() == {"ok": False, "message": "No Jev API key saved."}
    respx.get("https://api.typesafe.ai/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    assert client.post("/api/settings/test/jev", json={"api_key": SECRET}).json() == {"ok": True, "message": "Connected"}
    respx.get("https://api.typesafe.ai/v1/models").mock(return_value=httpx.Response(401, json={"detail": "bad"}))
    bad = client.post("/api/settings/test/jev", json={"api_key": "wrong"}).json()
    assert bad["ok"] is False and "401" in bad["message"]

    url = "https://api.cloudflare.com/client/v4/accounts/acc1/ai/run/@cf/zai-org/glm-4.7-flash"
    respx.post(url).mock(return_value=httpx.Response(200, json={
        "success": True, "result": {"choices": [{"message": {"content": "OK"}}], "usage": {}}}))
    ok = client.post("/api/settings/test/cloudflare", json={"account_id": "acc1", "api_token": CF_TOKEN}).json()
    assert ok == {"ok": True, "message": "Connected"}
    assert client.post("/api/settings/test/cloudflare", json={}).json()["ok"] is False


def test_openapi_docs(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for p in ["/api/sessions", "/api/sessions/{sid}/runs", "/api/runs/{run_id}/cancel", "/api/runs/{run_id}/decisions",
              "/api/runs/{run_id}/items/{item_id}/restore", "/api/sessions/{sid}/undo", "/api/sessions/{sid}/redo",
              "/api/runs/{run_id}/compare", "/api/runs/{run_id}/export.json", "/api/runs/{run_id}/report.csv",
              "/api/settings", "/api/settings/test/jev", "/api/settings/test/cloudflare"]:
        assert p in paths, p


@pytest.mark.parametrize("fmt", ["openai", "anthropic"])
def test_restore_folded_item_reinserts_turn_after_summary(client, fmt):
    """Items folded into the summary come back verbatim as a tool call + result pair."""
    msgs = build([Step(f"cat src/m{i}.ts", "\n".join(f"line {j} of m{i}" for j in range(300))) for i in range(20)], fmt)
    s = upload(client, msgs, name=f"folded-{fmt}")
    r = client.post(f"/api/sessions/{s['id']}/runs?wait=true", json={"budget": 3000}).json()
    folded = [d for d in client.get(f"/api/runs/{r['id']}/decisions").json() if d["summarized"]]
    assert len(folded) >= 2
    early, late = folded[0], folded[1]

    # restore the later turn first, then the earlier one: originals must end up in original order
    v1 = client.post(f"/api/runs/{r['id']}/items/{late['item_id']}/restore")
    assert v1.status_code == 201, v1.text
    v2 = client.post(f"/api/runs/{v1.json()['id']}/items/{early['item_id']}/restore").json()
    out = client.get(f"/api/runs/{v2['id']}/export.json").json()

    sp = next(i for i, m in enumerate(out)
              if (m["content"] if isinstance(m["content"], str) else m["content"][0].get("text", "")).startswith(
                  "[JevCompact summary of"))
    e, l = early["message_index"], late["message_index"]
    expected = [msgs[e - 1], msgs[e], msgs[l - 1], msgs[l]]  # assistant call + tool result, twice
    assert out[sp + 1: sp + 5] == expected
    from jevcompact import parse_session, user_messages_lost

    parse_session(out)
    assert user_messages_lost(msgs, out) == 0
    if fmt == "openai":
        calls = {tc["id"] for m in out for tc in m.get("tool_calls") or []}
        results = {m["tool_call_id"] for m in out if m["role"] == "tool"}
    else:
        calls = {b["id"] for m in out if isinstance(m["content"], list) for b in m["content"] if b["type"] == "tool_use"}
        results = {b["tool_use_id"] for m in out if isinstance(m["content"], list)
                   for b in m["content"] if b["type"] == "tool_result"}
    assert calls == results

    rows = {d["item_id"]: d for d in client.get(f"/api/runs/{v2['id']}/decisions").json()}
    for d in (early, late):
        assert rows[d["item_id"]]["restored"] and rows[d["item_id"]]["action"] == "Kept"
        assert rows[d["item_id"]]["content_after"] == d["content"]
        assert "from the summary" in rows[d["item_id"]]["reason"]
    assert v2["tokens_after"] > r["tokens_after"]
    c = client.get(f"/api/runs/{v2['id']}/compare").json()
    assert sum(x["after"]["tokens"] for x in c["rows"] if x["after"]) == c["tokens_after"] == v2["tokens_after"]
    assert sum(1 for x in c["rows"] if x["marker"] == "Restored") == 2
    assert client.post(f"/api/runs/{v2['id']}/items/{early['item_id']}/restore").status_code == 409
    assert client.post(f"/api/sessions/{s['id']}/undo").json()["current_run_id"] == v1.json()["id"]
