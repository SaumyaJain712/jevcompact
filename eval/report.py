"""Build eval/results.md and docs/figures/*.png from the CSVs written by run_eval.py.

Real (Jev + Cloudflare) and mock results are kept in separate tables and separate
figures; every title says which one it is.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
FIG = ROOT / "docs" / "figures"
METHODS = ["fifo", "plain", "prune_only", "hybrid"]
LABEL = {"fifo": "FIFO sliding window", "plain": "Plain summary only", "prune_only": "Jev prune only",
         "hybrid": "JevCompact hybrid"}
# Categorical slots 1-4 of the validated reference palette (fixed order, one per method).
COLOR = {"fifo": "#2a78d6", "plain": "#eb6834", "prune_only": "#1baf7a", "hybrid": "#eda100"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
MODE_TITLE = {"real": "real: Jev + Cloudflare Workers AI", "mock": "mock: MockJudge + MockSummarizer"}


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def style(ax, title: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=12, pad=12)
    ax.set_ylabel(ylabel, color=INK2)
    ax.tick_params(colors=INK2, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def grouped_bars(rows: list[dict], metric: str, ylabel: str, title: str, out: Path, ymax: float | None = None) -> None:
    sessions = sorted({r["session"] for r in rows})
    fig, ax = plt.subplots(figsize=(11, 4.8), dpi=150, facecolor=SURFACE)
    width = 0.2
    for k, m in enumerate(METHODS):
        vals = [f(next((r[metric] for r in rows if r["session"] == s and r["method"] == m), 0)) for s in sessions]
        xs = [i + (k - 1.5) * (width + 0.01) for i in range(len(sessions))]
        bars = ax.bar(xs, vals, width, color=COLOR[m], label=LABEL[m], edgecolor=SURFACE, linewidth=1)
        for b, v in zip(bars, vals):  # visible values: relief for the lighter slots
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + (ymax or max(vals + [1])) * 0.01, f"{v:.0f}",
                    ha="center", va="bottom", fontsize=7, color=INK2)
    ax.set_xticks(range(len(sessions)), sessions, fontsize=8, color=INK2)
    if ymax:
        ax.set_ylim(0, ymax)
    style(ax, title, ylabel)
    ax.legend(frameon=False, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.1), fontsize=8, labelcolor=INK2)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def clipping_chart(rows: list[dict], mode: str, out: Path) -> None:
    clips = ["300", "1000", "unclipped"]
    over = [r for r in rows if r["status"] != "Under budget"]
    if not over:
        return
    kept = [sum(f(r["needed_kept_pct"]) for r in over if r["clip"] == c) / max(1, sum(r["clip"] == c for r in over))
            for c in clips]
    cost = [sum(f(r["jev_cost_usd"]) for r in over if r["clip"] == c) / max(1, sum(r["clip"] == c for r in over))
            for c in clips]
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4), dpi=150, facecolor=SURFACE)
    for ax, vals, lab, fmt in [(a, kept, "Needed items kept verbatim (%)", "{:.1f}%"),
                               (b, cost, "Jev cost per compaction (USD)", "${:.4f}")]:
        bars = ax.bar(clips, vals, 0.5, color=COLOR["prune_only"], edgecolor=SURFACE)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), fmt.format(v), ha="center", va="bottom",
                    fontsize=8, color=INK2)
        style(ax, lab, "")
        ax.set_xlabel("jev_item_max_tokens", color=INK2)
    b.axhline(0.002, color=INK2, linewidth=1, linestyle="--")
    b.text(2.3, 0.002, " $0.002 target", va="bottom", ha="right", fontsize=8, color=INK2)
    fig.suptitle(f"Clipping trade-off, Jev prune only, mean over sessions ({MODE_TITLE[mode]})", x=0.01, ha="left",
                 color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def sweep_chart(rows: list[dict], mode: str, out: Path) -> None:
    if not rows:
        return
    pts = sorted(((f(r["tool_tokens_saved_pct"]), f(r["needed_kept_pct"]), r) for r in rows), key=lambda p: p[0])
    front, best = [], -1.0
    for x, y, r in sorted(pts, key=lambda p: (-p[0], -p[1])):
        if y > best:
            front.append((x, y))
            best = y
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150, facecolor=SURFACE)
    ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=14, color=GRID, edgecolor=INK2, linewidth=0.3,
               label="keep/drop grid")
    front.sort()
    ax.plot([p[0] for p in front], [p[1] for p in front], color=COLOR["hybrid"], linewidth=2, label="best trade-off")
    for x, y, r in pts:
        if r["preset"]:
            ax.scatter([x], [y], s=60, color=COLOR["fifo"], edgecolor=SURFACE, linewidth=2, zorder=3)
            ax.annotate(f"{r['preset']} ({r['keep']}/{r['drop']})", (x, y), xytext=(6, -12), textcoords="offset points",
                        fontsize=8, color=INK)
    ax.axhline(95, color=INK2, linewidth=1, linestyle="--")
    ax.text(ax.get_xlim()[0], 95, " 95% target", va="bottom", fontsize=8, color=INK2)
    style(ax, f"Threshold sweep: needed items kept vs tool tokens saved ({MODE_TITLE[mode]})", "Needed items kept (%)")
    ax.set_xlabel("Tool-output tokens saved by pruning (%)", color=INK2)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="lower left")
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def md_table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + [
        "| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def mode_section(mode: str) -> list[str]:
    suffix = "" if mode == "real" else "_mock"
    rows = read(EVAL / f"results{suffix}.csv")
    title = "Main results (real)" if mode == "real" else "Secondary results (mock)"
    out = [f"## {title} — {MODE_TITLE[mode]}", ""]
    if not rows:
        return out + ["Not run yet." + (" The real run needs JEV_API_KEY, CF_ACCOUNT_ID and CF_API_TOKEN." if mode == "real" else ""), ""]
    meta_p = EVAL / f"run{suffix}.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        out += [f"Run on {meta['date']} · judge: {meta['judge']} · summarizer: {meta['summarizer']} · "
                f"budget {meta['budget']:,} tokens · {meta.get('summaries_generated', 0)} new summaries, "
                f"{meta.get('neurons_spent_today', 0):,.0f} neurons spent today.", ""]
    over_sessions = sorted({r["session"] for r in rows if int(r["tokens_before"]) > 120_000})
    agg = []
    for m in METHODS:
        rs = [r for r in rows if r["method"] == m and r["session"] in over_sessions]
        n = max(1, len(rs))
        agg.append([f"{LABEL[m]} ({mode})",
                    f"{sum(f(r['pct_saved']) for r in rs) / n:.1f}%",
                    f"{100 * sum(f(r['needed_kept']) for r in rs) / max(1, sum(f(r['needed_items']) for r in rs)):.1f}%",
                    int(sum(f(r["user_messages_lost"]) for r in rs)),
                    "n/a" if m in ("fifo", "plain", "prune_only") else int(sum(f(r["invented_lines_removed"]) for r in rs)),
                    f"{sum(f(r['latency_ms']) for r in rs) / n / 1000:.2f} s",
                    f"${sum(f(r['jev_cost_usd']) for r in rs) / n:.4f}",
                    f"{sum(f(r['cf_neurons']) for r in rs) / n:,.0f}",
                    sum(r["status"] == "Fell back" for r in rs)])
    out += [f"### Averages over the {len(over_sessions)} sessions above the 120k budget ({mode})", ""]
    out += md_table(["Method", "Tokens saved", "Needed items kept", "User msgs lost", "Invented lines removed",
                     "Latency", "Jev cost", "CF neurons", "Fell back"], agg)
    out += ["", f"### Per session ({mode})", ""]
    per = [[r["session"], f"{LABEL[r['method']]} ({mode})", r["status"], f"{int(r['tokens_before']):,}",
            f"{int(r['tokens_after']):,}", f"{r['pct_saved']}%", f"{r['needed_kept']}/{r['needed_items']}",
            r["needed_truncated"], r["needed_removed"], r["user_messages_lost"], r["invented_lines_removed"],
            f"{f(r['latency_ms']) / 1000:.2f} s", f"${f(r['jev_cost_usd']):.4f}", f"{f(r['cf_neurons']):,.0f}"]
           for r in rows]
    out += md_table(["Session", "Method", "Status", "Tokens before", "Tokens after", "Saved", "Needed kept",
                     "Needed cut", "Needed removed", "User msgs lost", "Invented removed", "Latency", "Jev cost",
                     "CF neurons"], per)
    falls = [r for r in rows if r["fallback_reason"]]
    if falls:
        out += ["", "Fallbacks: " + "; ".join(f"{r['session']} / {LABEL[r['method']]}: {r['fallback_reason']}" for r in falls)]

    clips = read(EVAL / f"clipping{suffix}.csv")
    if clips:
        out += ["", f"### Clipping trade-off ({mode}, Jev prune only)", ""]
        tab = []
        for c in ["300", "1000", "unclipped"]:
            rs = [r for r in clips if r["clip"] == c and r["status"] != "Under budget"]
            n = max(1, len(rs))
            tab.append([c, f"{sum(f(r['needed_kept_pct']) for r in rs) / n:.1f}%", f"{sum(f(r['pct_saved']) for r in rs) / n:.1f}%",
                        f"{sum(f(r['jev_input_tokens']) for r in rs) / n:,.0f}", f"${sum(f(r['jev_cost_usd']) for r in rs) / n:.4f}",
                        f"{sum(f(r['scoring_latency_ms']) for r in rs) / n:.0f} ms"])
        out += md_table(["jev_item_max_tokens", "Needed kept (mean)", "Tokens saved", "Jev input tokens", "Jev cost",
                         "Scoring latency"], tab)
    sweep = read(EVAL / f"threshold_sweep{suffix}.csv")
    if sweep:
        out += ["", f"### Threshold sweep ({mode}; recorded Jev scores re-classified, no extra calls)", ""]
        presets = [r for r in sweep if r["preset"]]
        ok = sorted((r for r in sweep if f(r["needed_kept_pct"]) >= 95), key=lambda r: -f(r["tool_tokens_saved_pct"]))
        rows_t = [[r["preset"] or "best ≥95% kept", r["keep"], r["drop"], f"{r['needed_kept_pct']}%",
                   f"{r['tool_tokens_saved_pct']}%"] for r in presets + ok[:1]]
        out += md_table(["Setting", "Keep", "Drop", "Needed kept", "Tool tokens saved"], rows_t)
        out += ["", f"Full grid: `eval/threshold_sweep{suffix}.csv`."]
    out += ["", f"Figures: `docs/figures/tokens_saved_{mode}.png`, `needed_kept_{mode}.png`, "
                f"`clipping_{mode}.png`, `threshold_sweep_{mode}.png`.", ""]
    return out


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    md = ["# Evaluation results", "",
          "Four methods on every sample in `data/samples/`: FIFO sliding window, plain summary only, Jev prune only, "
          "and the full JevCompact hybrid. Real and mock runs are reported separately and never combined.", "",
          "**Metrics.** *Needed items kept*: hand-labelled needed tool results (`eval/LABELS.md`) still present "
          "word for word in the compacted session (pinned or kept; truncated, dropped or summarized do not count). "
          "*Invented lines removed*: summary lines the Jev check found no source for (hybrid only). *Jev cost* uses "
          "Jev's billed `usage.input_tokens` × $0.042/M (mock: tiktoken counts). *CF neurons*: Cloudflare cost of the "
          "summary (first generation; re-runs reuse the cached summary).", ""]
    for mode in ("real", "mock"):
        md += mode_section(mode)
        suffix = "" if mode == "real" else "_mock"
        rows = read(EVAL / f"results{suffix}.csv")
        if rows:
            grouped_bars(rows, "pct_saved", "Tokens saved (%)", f"Tokens saved by method ({MODE_TITLE[mode]})",
                         FIG / f"tokens_saved_{mode}.png", 100)
            grouped_bars(rows, "needed_kept_pct", "Needed items kept verbatim (%)",
                         f"Hand-labelled needed items kept ({MODE_TITLE[mode]})", FIG / f"needed_kept_{mode}.png", 110)
        clipping_chart(read(EVAL / f"clipping{suffix}.csv"), mode, FIG / f"clipping_{mode}.png")
        sweep_chart(read(EVAL / f"threshold_sweep{suffix}.csv"), mode, FIG / f"threshold_sweep_{mode}.png")
    (EVAL / "results.md").write_text("\n".join(md) + "\n")
    print("wrote eval/results.md and docs/figures/")


if __name__ == "__main__":
    main()
