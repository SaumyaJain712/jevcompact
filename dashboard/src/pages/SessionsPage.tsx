import { DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, SessionRow, UPLOAD_ERROR, validateSessionFile } from "../api";
import { Banner, k, n, PageHeader, StatusChip } from "../components/ui";

type Filter = "" | "Compacted" | "Fell back";
const FILTERS: { label: string; value: Filter }[] = [
  { label: "All", value: "" },
  { label: "Compacted", value: "Compacted" },
  { label: "Fell back", value: "Fell back" },
];

export default function SessionsPage() {
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.sessions(q, filter).then(setRows).catch((e) => setError(String(e.message ?? e)));
  }, [q, filter]);

  useEffect(() => {
    const t = setTimeout(load, 150);
    return () => clearTimeout(t);
  }, [load]);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (!(await validateSessionFile(file))) {
      setError(UPLOAD_ERROR);
      return;
    }
    setBusy(true);
    try {
      const s = await api.upload(file);
      navigate(`/sessions/${s.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const choose = () => fileInput.current?.click();

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    handleFile(e.dataTransfer.files[0]);
  }

  return (
    <>
      <PageHeader
        title="Sessions"
        sub="Agent sessions you have uploaded. Each one is compacted when it passes the token budget."
        actions={
          <button className="btn btn-primary" onClick={choose} disabled={busy}>
            {busy ? "Uploading…" : "Upload session"}
          </button>
        }
      />
      <input
        ref={fileInput}
        type="file"
        accept=".json,application/json"
        className="sr-only"
        aria-label="Session file"
        data-testid="file-input"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      {error && (
        <Banner kind="error" label="Error" actions={[{ label: "Choose another file", onClick: choose }]}>
          {error}
        </Banner>
      )}

      <div className="toolbar">
        <input
          className="input"
          type="search"
          placeholder="Search sessions"
          aria-label="Search sessions"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="filters" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button key={f.label} className="filter" aria-pressed={filter === f.value} onClick={() => setFilter(f.value)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th className="num">Messages</th>
              <th className="num">Tokens</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows?.map((s) => (
              <tr key={s.id} onClick={() => navigate(`/sessions/${s.id}`)}>
                <td>
                  <a className="session-name" href={`/sessions/${s.id}`} onClick={(e) => e.preventDefault()}>
                    {s.name}
                  </a>
                </td>
                <td className="num">{n(s.message_count)}</td>
                <td className="num" title={`${n(s.tokens_before)} → ${n(s.tokens_after)} tokens`}>
                  {k(s.tokens_before)} → {k(s.tokens_after)}
                </td>
                <td>
                  <StatusChip status={s.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows && rows.length === 0 && (
          <div className="empty">{q || filter ? "No sessions match." : "No sessions yet. Upload one to start."}</div>
        )}
      </div>

      <div
        className={`dropzone ${over ? "over" : ""}`}
        data-testid="dropzone"
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <strong>Drop a session file here</strong>
        <div>Only .json files: an OpenAI or Anthropic message array. It is checked before upload.</div>
      </div>
    </>
  );
}
