import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, Compare, CompareCell, CompareRow, SessionDetail } from "../api";
import { Banner, judgeCost, n, PageHeader, RoleTag, seconds } from "../components/ui";

const MARKER_COLOR: Record<NonNullable<CompareRow["marker"]>, string> = {
  Dropped: "red",
  Truncated: "amber",
  Summarized: "grey",
  Summary: "green",
  Restored: "green",
};

function Cell({ cell, side, marker }: { cell: CompareCell | null; side: "before" | "after"; marker: CompareRow["marker"] }) {
  if (!cell) {
    return (
      <div className={`cell blank ${side}`} aria-label={side === "after" ? "Removed: folded into the summary" : "Not in original"}>
        {side === "after" && marker === "Summarized" && <span className="chip grey">In summary</span>}
      </div>
    );
  }
  const showMarker = marker && (side === "after" || marker === "Summarized");
  return (
    <div className={`cell ${side}`}>
      <RoleTag role={cell.role} />
      <span className={`t ${cell.role === "USER" || cell.role === "SUMMARY" ? "" : "mono"}`} title={cell.text ?? cell.title}>
        {cell.title}
      </span>
      {showMarker && side === "after" ? <span className={`chip ${MARKER_COLOR[marker!]}`}>{marker}</span> : <span />}
      <span className="tokens">{n(cell.tokens)}</span>
    </div>
  );
}

export default function ComparePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .session(id)
      .then(async (d) => {
        setDetail(d);
        if (d.current_run) setCmp(await api.compare(d.current_run.id));
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [id]);

  const runId = detail?.current_run?.id;
  const download = (url: string) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <>
      <PageHeader
        title="Compare and export"
        sub={detail ? detail.name : "Loading…"}
        actions={
          <>
            <button className="btn" disabled={!runId} onClick={() => runId && download(api.reportCsvUrl(runId))}>
              Export report (CSV)
            </button>
            <button className="btn btn-primary" disabled={!runId} onClick={() => runId && download(api.exportJsonUrl(runId))}>
              Export JSON
            </button>
          </>
        }
      />
      {error && (
        <Banner kind="error" label="Error" actions={[{ label: "Back to sessions", onClick: () => navigate("/sessions") }]}>
          {error}
        </Banner>
      )}
      {detail && !detail.current_run && (
        <div className="card empty">
          {detail.version === 0
            ? "This is the original session (version 0), so there is nothing to compare. Use Redo or Re-run on the review screen."
            : "This session has not been compacted yet."}
        </div>
      )}
      {cmp && (
        <>
          <div className="card summary-bar" data-testid="summary-bar">
            <span>{judgeCost(cmp)}</span>
            <span className="sep">·</span>
            <span>{seconds(cmp.latency_ms)}</span>
            <span className="sep">·</span>
            <span>{cmp.dropped} dropped</span>
            <span className="sep">·</span>
            <span>{cmp.truncated} truncated</span>
            <span className="sep">·</span>
            <span>
              {cmp.user_messages_touched} user {cmp.user_messages_touched === 1 ? "message" : "messages"} touched
            </span>
            {cmp.neurons > 0 && (
              <>
                <span className="sep">·</span>
                <span>Cloudflare {n(Math.round(cmp.neurons))} neurons</span>
              </>
            )}
          </div>
          <div className="card compare">
            <div className="col-head">
              <span>Before</span>
              <span className="tokens">{n(cmp.tokens_before)} tokens</span>
            </div>
            <div className="col-head">
              <span>After</span>
              <span className="tokens">{n(cmp.tokens_after)} tokens</span>
            </div>
            {cmp.rows.map((r, i) => (
              <div key={i} style={{ display: "contents" }} data-testid="compare-row">
                <Cell cell={r.before} side="before" marker={r.marker} />
                <Cell cell={r.after} side="after" marker={r.marker} />
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}
