import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError, Decision, Preset, SessionDetail, waitForRun } from "../api";
import { ActionChip, Banner, BannerAction, k, n, PageHeader, RoleTag, seconds, StatusChip, usd } from "../components/ui";

const PRESETS: Record<Exclude<Preset, "custom">, [number, number]> = {
  conservative: [0.3, 0.05],
  balanced: [0.5, 0.1],
  aggressive: [0.7, 0.2],
};

const isRestorable = (d: Decision) => !d.restored && (d.summarized || d.action === "Dropped" || d.action === "Cut");

export default function ReviewPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [selected, setSelected] = useState(0);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [keep, setKeep] = useState(0.5);
  const [drop, setDrop] = useState(0.1);
  const [preset, setPreset] = useState<Preset>("balanced");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      let d = await api.session(id);
      // a freshly uploaded session may still be compacting
      const running = d.runs.find((r) => r.status === "Running");
      if (!d.current_run && running) {
        setBusy("Compacting…");
        await waitForRun(running.id);
        d = await api.session(id);
        setBusy(null);
      }
      setDetail(d);
      if (d.current_run) {
        setDecisions(await api.decisions(d.current_run.id));
        setKeep(d.current_run.keep_threshold);
        setDrop(d.current_run.drop_threshold);
        setPreset(d.current_run.preset);
      } else {
        // version 0: the original upload, nothing compacted
        const items = await api.items(id);
        setDecisions(
          items.map((it) => ({
            ...it,
            item_id: `original-${it.item_index}`,
            score: null,
            action: "Kept" as const,
            reason: "Original session (version 0): nothing removed.",
            tokens_after: it.tokens,
            summarized: false,
            restored: false,
            content_after: it.content,
            created_at: "",
          })),
        );
      }
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "This session no longer exists." : String(e));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const run = detail?.current_run ?? null;
  const valid = keep > drop;

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const rerun = () =>
    act("Running…", async () => {
      const r = await api.startRun(id, { preset, keep_threshold: keep, drop_threshold: drop });
      await waitForRun(r.id);
    });
  const undo = () => act("Undoing…", () => api.undo(id));
  const redo = () => act("Redoing…", () => api.redo(id));
  const restore = (d: Decision) => run && act("Restoring…", () => api.restore(run.id, d.item_id));

  // Keyboard: J/K move, R restore, U undo
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName) || busy) return;
      const key = e.key.toLowerCase();
      if (key === "j") setSelected((s) => Math.min(s + 1, decisions.length - 1));
      else if (key === "k") setSelected((s) => Math.max(s - 1, 0));
      else if (key === "r" && run && decisions[selected] && isRestorable(decisions[selected])) restore(decisions[selected]);
      else if (key === "u" && detail?.can_undo) undo();
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${selected}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const dropped = useMemo(() => decisions.filter((d) => d.action === "Dropped" && !d.restored), [decisions]);
  const notable = useMemo(
    () => [...dropped].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0],
    [dropped],
  );

  function setPresetAndSliders(p: Preset) {
    setPreset(p);
    if (p !== "custom") [setKeep, setDrop].forEach((f, i) => f(PRESETS[p][i]));
  }

  const toggle = (i: number) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  const viewLog = () => {
    setShowLog(true);
    setTimeout(() => logRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  const banners: JSX.Element[] = [];
  if (run?.status === "Fell back") {
    const timeout = (run.fallback_reason ?? "").includes("didn't respond");
    banners.push(
      <Banner
        key="fb"
        kind="warning"
        label="Fell back"
        actions={[
          { label: "Retry with Jev", onClick: rerun },
          { label: "View log", onClick: viewLog, link: true },
        ]}
      >
        {timeout
          ? "Jev didn't respond in 5 s. We used the plain summary instead, so nothing was lost."
          : `${run.fallback_reason}. We used the plain summary instead, so nothing was lost.`}
      </Banner>,
    );
  }
  if (run?.status === "Failed") {
    banners.push(
      <Banner key="fail" kind="error" label="Error" actions={[{ label: "Re-run", onClick: rerun }]}>
        {run.error}
      </Banner>,
    );
  }
  if (run && run.kind === "run" && notable) {
    const acts: BannerAction[] = [
      { label: "Undo", onClick: undo },
      { label: "Restore one", onClick: () => restore(notable) },
    ];
    banners.push(
      <Banner key="drop" kind="info" label="Dropped" actions={acts}>
        {dropped.length} {dropped.length === 1 ? "item" : "items"} dropped. "{notable.title}" was among them.
      </Banner>,
    );
  }

  if (error && !detail) {
    return (
      <>
        <PageHeader title="Session review" />
        <Banner kind="error" label="Error" actions={[{ label: "Back to sessions", onClick: () => navigate("/sessions") }]}>
          {error}
        </Banner>
      </>
    );
  }
  if (!detail) return <PageHeader title="Session review" sub={busy ?? "Loading…"} />;

  const original = !run && detail.version === 0;
  const headline = run ? (
    <span className="headline" data-testid="headline">
      {k(run.tokens_before)} → {k(run.tokens_after)} tokens ({Math.round(run.percent_saved ?? 0)}% smaller) · Jev cost{" "}
      {usd(run.jev_cost_usd)} · {seconds(run.latency_ms)}
    </span>
  ) : original ? (
    <span className="headline" data-testid="headline">
      {k(detail.tokens_before)} → {k(detail.tokens_before)} tokens (0% smaller) · original session, version 0
    </span>
  ) : (
    "Not compacted yet"
  );

  return (
    <>
      <PageHeader
        title={detail.name}
        sub={
          <span className="row">
            {headline} {run ? <StatusChip status={run.status} /> : original && <StatusChip status="Original" />}
          </span>
        }
        actions={
          <>
            <button className="btn" onClick={undo} disabled={!detail.can_undo || !!busy}>
              Undo
            </button>
            <button className="btn" onClick={redo} disabled={!detail.can_redo || !!busy}>
              Redo
            </button>
            <button className="btn btn-primary" onClick={() => navigate(`/sessions/${id}/compare`)} disabled={!run}>
              Compare
            </button>
          </>
        }
      />
      {banners}
      {error && (
        <Banner kind="error" label="Error" actions={[{ label: "Dismiss", onClick: () => setError(null) }]}>
          {error}
        </Banner>
      )}

      <div className="review">
        <div>
          <div className="card items" ref={listRef} role="list" aria-label="Items">
            {decisions.map((d, i) => (
              <div
                key={d.item_id}
                className={`item ${i === selected ? "selected" : ""}`}
                data-index={i}
                data-testid="item"
                role="listitem"
              >
                <div
                  className="item-head"
                  role="button"
                  tabIndex={0}
                  aria-expanded={open.has(i)}
                  onClick={() => {
                    setSelected(i);
                    toggle(i);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggle(i);
                    }
                  }}
                >
                  <RoleTag role={d.role} />
                  <div className="item-title">
                    {d.role === "USER" ? d.title : <span className="mono">{d.title}</span>}
                    {d.summarized && !d.restored && <span className="tag"> · In summary</span>}
                    {d.restored && <span className="tag"> · Restored</span>}
                  </div>
                  <div className="tokens">{n(d.tokens)} tok</div>
                  <div>
                    {run ? (
                      <ActionChip action={d.action} score={d.score} />
                    ) : (
                      <span className="chip grey" data-testid="action-chip">
                        Original
                      </span>
                    )}
                  </div>
                  <div>
                    {run && isRestorable(d) && (
                      <button
                        className="btn btn-small"
                        disabled={!!busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          restore(d);
                        }}
                      >
                        Restore
                      </button>
                    )}
                  </div>
                </div>
                {open.has(i) && (
                  <div className="item-body">
                    <p className="reason">{d.reason}</p>
                    <pre className="output">{d.content}</pre>
                  </div>
                )}
              </div>
            ))}
            {decisions.length === 0 && <div className="empty">No items.</div>}
          </div>
          <p className="keys">
            <kbd>J</kbd>/<kbd>K</kbd> to move · <kbd>R</kbd> to restore · <kbd>U</kbd> to undo · click an item to
            show its full output
          </p>

          {showLog && (
            <div className="card summary-box" ref={logRef}>
              <div className="card-pad">
                <h2>Decision log</h2>
                <table className="log">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Item</th>
                      <th className="num">Score</th>
                      <th>Action</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisions.map((d) => (
                      <tr key={d.item_id}>
                        <td className="mono">{d.created_at.slice(11, 23)}</td>
                        <td>{d.title}</td>
                        <td className="num">{d.score === null ? "–" : d.score.toFixed(2)}</td>
                        <td>{d.action}</td>
                        <td>{d.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {run?.fallback_reason && <p className="keys">Fallback reason: {run.fallback_reason}</p>}
              </div>
            </div>
          )}
        </div>

        <aside className="card card-pad panel" aria-label="Thresholds">
          <h2>Thresholds</h2>
          <div className="field">
            <div className="slider-head">
              <label htmlFor="keep">Keep</label>
              <output htmlFor="keep">{keep.toFixed(2)}</output>
            </div>
            <input
              id="keep"
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={keep}
              onChange={(e) => {
                setKeep(Number(e.target.value));
                setPreset("custom");
              }}
            />
            <span className="hint">Kept verbatim at or above this score.</span>
          </div>
          <div className="field">
            <div className="slider-head">
              <label htmlFor="drop">Drop</label>
              <output htmlFor="drop">{drop.toFixed(2)}</output>
            </div>
            <input
              id="drop"
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={drop}
              onChange={(e) => {
                setDrop(Number(e.target.value));
                setPreset("custom");
              }}
            />
            <span className="hint">Dropped (and kept for recall) below this score. In between: truncated.</span>
            {!valid && <span className="error">Keep threshold must be higher than drop threshold.</span>}
          </div>
          <div className="field">
            <label htmlFor="preset">Preset</label>
            <select id="preset" className="input" value={preset} onChange={(e) => setPresetAndSliders(e.target.value as Preset)}>
              <option value="conservative">Conservative (0.30 / 0.05)</option>
              <option value="balanced">Balanced (0.50 / 0.10)</option>
              <option value="aggressive">Aggressive (0.70 / 0.20)</option>
              <option value="custom">Custom</option>
            </select>
          </div>
          <button className="btn" onClick={rerun} disabled={!valid || !!busy}>
            {busy ?? "Re-run"}
          </button>
        </aside>
      </div>
    </>
  );
}
