-- JevCompact SQLite schema. The ER diagram in docs/diagrams/er.mmd is generated
-- from this file by scripts/gen_er.py.
PRAGMA foreign_keys = ON;

-- An uploaded session. The original messages are never modified.
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    format          TEXT NOT NULL CHECK (format IN ('openai', 'anthropic')),
    message_count   INTEGER NOT NULL,
    tokens_before   INTEGER NOT NULL,
    tokens_after    INTEGER,
    -- 'Original' = undone back to version 0 (the uploaded session, uncompacted)
    status          TEXT CHECK (status IN ('Compacted', 'Fell back', 'Under budget', 'Original')),
    current_run_id  TEXT,
    created_at      TEXT NOT NULL
);

-- Original messages, one row per message (content stored as JSON).
CREATE TABLE IF NOT EXISTS messages (
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    "index"     INTEGER NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    tokens      INTEGER NOT NULL,
    PRIMARY KEY (session_id, "index")
);

-- Each run (compaction or restore) produces a new version of the session.
CREATE TABLE IF NOT EXISTS runs (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq                 INTEGER NOT NULL,
    kind                TEXT NOT NULL DEFAULT 'run' CHECK (kind IN ('run', 'restore')),
    parent_run_id       TEXT REFERENCES runs(id) ON DELETE SET NULL,
    preset              TEXT NOT NULL,
    keep_threshold      REAL NOT NULL,
    drop_threshold      REAL NOT NULL,
    budget              INTEGER NOT NULL,
    judge               TEXT NOT NULL,
    summarizer          TEXT NOT NULL,
    jev_cost_usd        REAL NOT NULL DEFAULT 0,
    jev_input_tokens    INTEGER NOT NULL DEFAULT 0,
    jev_requests        INTEGER NOT NULL DEFAULT 0,
    neurons             REAL NOT NULL DEFAULT 0,
    latency_ms          REAL NOT NULL DEFAULT 0,
    scoring_latency_ms  REAL NOT NULL DEFAULT 0,
    tokens_before       INTEGER,
    tokens_after        INTEGER,
    user_messages_lost  INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL CHECK (status IN
                        ('Running', 'Compacted', 'Fell back', 'Under budget', 'Cancelled', 'Failed')),
    fallback_reason     TEXT,
    error               TEXT,
    superseded          INTEGER NOT NULL DEFAULT 0,
    config_json         TEXT,
    output_json         TEXT,
    index_map_json      TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE (session_id, seq)
);

-- One row per item per run: the decision log (FR9).
CREATE TABLE IF NOT EXISTS decisions (
    run_id         TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    message_index  INTEGER NOT NULL,
    item_id        TEXT NOT NULL,
    item_index     INTEGER NOT NULL,
    block_index    INTEGER,
    role           TEXT NOT NULL CHECK (role IN ('USER', 'TOOL', 'ERROR')),
    title          TEXT NOT NULL,
    score          REAL,
    action         TEXT NOT NULL CHECK (action IN ('Pinned', 'Kept', 'Cut', 'Dropped')),
    reason         TEXT NOT NULL,
    tokens         INTEGER NOT NULL,
    tokens_after   INTEGER NOT NULL,
    summarized     INTEGER NOT NULL DEFAULT 0,
    restored       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (run_id, item_index)
);

-- Full text of dropped / cut items, restorable verbatim.
CREATE TABLE IF NOT EXISTS recall_cache (
    item_id       TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    full_content  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    run_id             TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    text               TEXT NOT NULL,
    lines_removed      INTEGER NOT NULL,
    removed_lines_json TEXT NOT NULL,
    checked            INTEGER NOT NULL
);

-- Key/value settings. Secrets (API keys) are Fernet-encrypted (encrypted = 1).
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    encrypted  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_decisions_run ON decisions(run_id);
