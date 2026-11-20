// Typed client for the JevCompact FastAPI server (/api).

export type Status = "Compacted" | "Fell back" | "Under budget" | "Original";
export type RunStatus = Status | "Running" | "Cancelled" | "Failed";
export type Action = "Pinned" | "Kept" | "Cut" | "Dropped";
export type Role = "USER" | "TOOL" | "ERROR";
export type Preset = "conservative" | "balanced" | "aggressive" | "custom";

export interface SessionRow {
  id: string;
  name: string;
  format: "openai" | "anthropic";
  message_count: number;
  tokens_before: number;
  tokens_after: number | null;
  status: Status | null;
  current_run_id: string | null;
  created_at: string;
}

export interface RunSummary {
  id: string;
  seq: number;
  kind: "run" | "restore";
  status: RunStatus;
  superseded: number;
  created_at: string;
}

export interface Run {
  id: string;
  session_id: string;
  seq: number;
  kind: "run" | "restore";
  parent_run_id: string | null;
  preset: Preset;
  keep_threshold: number;
  drop_threshold: number;
  budget: number;
  judge: string;
  summarizer: string;
  jev_cost_usd: number;
  jev_input_tokens: number;
  neurons: number;
  latency_ms: number;
  scoring_latency_ms: number;
  tokens_before: number | null;
  tokens_after: number | null;
  status: RunStatus;
  fallback_reason: string | null;
  error: string | null;
  percent_saved: number | null;
  counts: Record<Action, number>;
  summary: { text: string; lines_removed: number; removed_lines: string[]; checked: number } | null;
}

export interface SessionDetail extends SessionRow {
  current_run: Run | null;
  runs: RunSummary[];
  /** 0 = the original upload; 1.. = runs and restores */
  version: number;
  can_undo: boolean;
  can_redo: boolean;
}

export interface Decision {
  item_id: string;
  item_index: number;
  message_index: number;
  role: Role;
  title: string;
  score: number | null;
  action: Action;
  reason: string;
  tokens: number;
  tokens_after: number;
  summarized: boolean;
  restored: boolean;
  content: string;
  content_after: string | null;
  created_at: string;
}

export interface OriginalItem {
  item_index: number;
  message_index: number;
  role: Role;
  title: string;
  tokens: number;
  content: string;
}

export interface CompareCell {
  role: string;
  title: string;
  tokens: number;
  index?: number;
  text?: string;
}

export interface CompareRow {
  before: CompareCell | null;
  after: CompareCell | null;
  marker: "Dropped" | "Truncated" | "Summarized" | "Summary" | "Restored" | null;
}

export interface Compare {
  run_id: string;
  status: RunStatus;
  tokens_before: number;
  tokens_after: number;
  jev_cost_usd: number;
  latency_ms: number;
  neurons: number;
  dropped: number;
  truncated: number;
  user_messages_touched: number;
  rows: CompareRow[];
}

export interface Settings {
  budget: number;
  keep_threshold: number;
  drop_threshold: number;
  preset: Preset;
  fallback_enabled: boolean;
  never_drop_errors: true;
  jev_api_key_set: boolean;
  jev_api_key_masked: string | null;
  cf_api_token_set: boolean;
  cf_api_token_masked: string | null;
  cf_account_id: string;
  judge: string;
  summarizer: string;
}

export interface TestResult {
  ok: boolean;
  message: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  sessions: (q = "", status = "") => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    return req<SessionRow[]>(`/sessions?${p}`);
  },
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<SessionRow & { run_id: string | null }>("/sessions", { method: "POST", body: fd });
  },
  session: (id: string) => req<SessionDetail>(`/sessions/${id}`),
  run: (id: string) => req<Run>(`/runs/${id}`),
  items: (sid: string) => req<OriginalItem[]>(`/sessions/${sid}/items`),
  decisions: (runId: string) => req<Decision[]>(`/runs/${runId}/decisions`),
  startRun: (sid: string, params: { preset?: Preset; keep_threshold?: number; drop_threshold?: number }) =>
    req<Run>(`/sessions/${sid}/runs`, json(params)),
  restore: (runId: string, itemId: string) => req<Run>(`/runs/${runId}/items/${itemId}/restore`, { method: "POST" }),
  undo: (sid: string) => req<{ current_run_id: string | null }>(`/sessions/${sid}/undo`, { method: "POST" }),
  redo: (sid: string) => req<{ current_run_id: string | null }>(`/sessions/${sid}/redo`, { method: "POST" }),
  compare: (runId: string) => req<Compare>(`/runs/${runId}/compare`),
  settings: () => req<Settings>("/settings"),
  saveSettings: (s: Record<string, unknown>) => req<Settings>("/settings", { method: "PUT", body: JSON.stringify(s) }),
  resetSettings: () => req<Settings>("/settings/reset", { method: "POST" }),
  testJev: (api_key?: string) => req<TestResult>("/settings/test/jev", json({ api_key: api_key || null })),
  testCloudflare: (account_id?: string, api_token?: string) =>
    req<TestResult>("/settings/test/cloudflare", json({ account_id: account_id || null, api_token: api_token || null })),
  exportJsonUrl: (runId: string) => `/api/runs/${runId}/export.json`,
  reportCsvUrl: (runId: string) => `/api/runs/${runId}/report.csv`,
};

export const UPLOAD_ERROR = "This file isn't a message list. We expected a JSON array of {role, content}.";

/** Same rules as the server: a non-empty JSON array of {role, content} objects. */
export async function validateSessionFile(file: File): Promise<boolean> {
  if (!file.name.toLowerCase().endsWith(".json")) return false;
  try {
    const data: unknown = JSON.parse(await file.text());
    return (
      Array.isArray(data) &&
      data.length > 0 &&
      data.every(
        (m) =>
          m !== null &&
          typeof m === "object" &&
          typeof (m as Record<string, unknown>).role === "string" &&
          ("content" in (m as object) || "tool_calls" in (m as object)),
      )
    );
  } catch {
    return false;
  }
}

/** Wait until a run is no longer Running. */
export async function waitForRun(runId: string, intervalMs = 400): Promise<Run> {
  for (;;) {
    const r = await api.run(runId);
    if (r.status !== "Running") return r;
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}
