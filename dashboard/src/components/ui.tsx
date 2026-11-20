import { ReactNode } from "react";
import type { Action, RunStatus } from "../api";

export function k(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`;
}

export function n(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : v.toLocaleString("en-US");
}

export function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(2)} s`;
}

export function usd(v: number): string {
  return `$${v.toFixed(4)}`;
}

const STATUS_COLOR: Record<string, string> = {
  Compacted: "green",
  "Fell back": "amber",
  "Under budget": "grey",
  Running: "navy",
  Failed: "red",
  Cancelled: "grey",
  Original: "grey",
};

export function StatusChip({ status }: { status: RunStatus | null }) {
  const s = status ?? "Running";
  return <span className={`chip ${STATUS_COLOR[s] ?? "grey"}`}>{s}</span>;
}

const ACTION_COLOR: Record<Action, string> = { Kept: "green", Cut: "amber", Dropped: "red", Pinned: "navy" };

export function ActionChip({ action, score }: { action: Action; score: number | null }) {
  const label = action === "Pinned" || score === null ? action : `${action} ${score.toFixed(2)}`;
  return (
    <span className={`chip ${ACTION_COLOR[action]}`} data-testid="action-chip">
      {label}
    </span>
  );
}

export function RoleTag({ role }: { role: string }) {
  return <span className={`role ${role}`}>{role}</span>;
}

export interface BannerAction {
  label: string;
  onClick: () => void;
  link?: boolean;
}

export function Banner({
  kind,
  label,
  children,
  actions,
}: {
  kind: "error" | "warning" | "info";
  label: string;
  children: ReactNode;
  actions: BannerAction[];
}) {
  return (
    <div className={`banner ${kind}`} role="alert">
      <div className="msg">
        <span className="label">{label}</span>
        <span>{children}</span>
      </div>
      <div className="actions">
        {actions.map((a) => (
          <button key={a.label} className={a.link ? "btn-link" : "btn btn-small"} onClick={a.onClick}>
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Switch({
  label,
  checked,
  onChange,
  locked = false,
}: {
  label: string;
  checked: boolean;
  onChange?: (v: boolean) => void;
  locked?: boolean;
}) {
  return (
    <div className="switch" aria-disabled={locked}>
      <button
        type="button"
        className="track"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={locked}
        onClick={() => onChange?.(!checked)}
      />
      <span className="state" style={{ color: checked ? "var(--green)" : "var(--grey)" }}>
        {checked ? "On" : "Off"}
      </span>
      <span>{label}</span>
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}
