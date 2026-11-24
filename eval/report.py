"""Build eval/results.md and docs/figures/*.png from the CSVs written by run_eval.py.

Real (Cloudflare judge standing in for Jev + Cloudflare summarizer) and mock results are kept
in separate tables and separate figures; every title names the judge.
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
LABEL = {"fifo": "FIFO sliding window", "plain": "Plain summary only", "prune_only": "Prune only (judge)",
         "hybrid": "JevCompact hybrid"}
# Categorical slots 1-4 of the validated reference palette (fixed order, one per method).
COLOR = {"fifo": "#2a78d6", "plain": "#eb6834", "prune_only": "#1baf7a", "hybrid": "#eda100"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BUDGET = 120_000


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def meta(mode: str) -> dict:
    p = EVAL / f"run{'' if mode == 'real' else '_mock'}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def mode_title(mode: str) -> str:
    m = meta(mode)
    if mode == "mock":
        return "mock: MockJudge + MockSummarizer"
    return f"real: {m.get('judge', 'Cloudflare judge, standing in for Jev')} + {m.get('summarizer', 'Cloudflare summarizer')}"


def short_title(mode: str) -> str:
    """For chart titles: the judge label in full, the summarizer shortened."""
    if mode == "mock":
        return "mock: MockJudge + MockSummarizer"
    return f"real: {meta(mode).get('judge', 'Cloudflare judge, standing in for Jev')}"


def f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def style(ax, title: str, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11, pad=12)
    ax.set_ylabel(ylabel, color=INK2)
    ax.tick_params(colors=INK2, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def default_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("thresholds", "default") in ("default", "n/a")]


def grouped_bars(rows: list[dict], metric: str, ylabel: str, title: str, out: Path, ymax: float | None = None) -> None:
    sessions = sorted({r["session"] for r in rows})
    fig, ax = plt.subplots(figsize=(11, 4.8), dpi=150, facecolor=SURFACE)
    width = 0.2
    for k, m in enumerate(METHODS):
        vals = [f(next((r[metric] for r in rows if r["session"] == s and r["method"] == m), 0)) for s in sessions]
        xs = [i + (k - 1.5) * (width + 0.01) for i in range(len(sessions))]
        bars = ax.bar(xs, vals, width, color=COLOR[m], label=LABEL[m], edgecolor=SURFACE, linewidth=1)
        for b, v in zip(bars, vals):
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
    over = [r for r in rows if r["status"] != "Under budget"]
    clips = [c for c in ["300", "1000", "unclipped"] if any(r["clip"] == c for r in over)]
    if not clips:
        return
    cost_key, cost_label, fmt = (("judge_neurons", "Judge neurons per compaction", "{:.0f}") if mode == "real"
                                 else ("jev_cost_usd", "Jev cost per compaction (USD, mock estimate)", "${:.4f}"))
    mean = lambda key, c: sum(f(r[key]) for r in over if r["clip"] == c) / max(1, sum(r["clip"] == c for r in over))  # noqa: E731
    kept = [mean("needed_kept_pct", c) for c in clips]
    cost = [mean(cost_key, c) for c in clips]
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4), dpi=150, facecolor=SURFACE)
    for ax, vals, lab, vf in [(a, kept, "Needed items kept verbatim (%)", "{:.1f}%"), (b, cost, cost_label, fmt)]:
        bars = ax.bar(clips, vals, 0.5, color=COLOR["prune_only"], edgecolor=SURFACE)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), vf.format(v), ha="center", va="bottom",
                    fontsize=8, color=INK2)
        style(ax, lab, "")
        ax.set_xlabel("jev_item_max_tokens (tokens per tool output shown to the judge)", color=INK2, fontsize=8)
    if mode == "mock":
        b.axhline(0.002, color=INK2, linewidth=1, linestyle="--")
    fig.suptitle(f"Clipping trade-off, prune only, mean over sessions\n({short_title(mode)})", x=0.01, ha="left",
                 color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def sweep_chart(rows: list[dict], mode: str, out: Path, tuned: tuple | None) -> None:
    if not rows:
        return
    pts = [(f(r["tool_tokens_saved_pct"]), f(r["needed_kept_pct"]), r) for r in rows]
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
        is_tuned = tuned and (f(r["keep"]), f(r["drop"])) == tuned
        if r["preset"] == "balanced" or is_tuned:
            ax.scatter([x], [y], s=60, color=COLOR["fifo"] if not is_tuned else COLOR["plain"], edgecolor=SURFACE,
                       linewidth=2, zorder=3)
            name = "default" if r["preset"] == "balanced" else "tuned"
            if r["preset"] == "balanced" and is_tuned:
                name = "default = tuned"
            ax.annotate(f"{name} ({r['keep']}/{r['drop']})", (x, y), xytext=(6, -12 if name != "tuned" else 6),
                        textcoords="offset points", fontsize=8, color=INK)
    ax.axhline(95, color=INK2, linewidth=1, linestyle="--")
    ax.text(ax.get_xlim()[0], 95, " 95% target", va="bottom", fontsize=8, color=INK2)
    ax.set_ylim(0, 105)
    style(ax, f"Threshold sweep over recorded scores\n({short_title(mode)})", "Needed items kept (%)")
    ax.set_xlabel("Tool-output tokens saved by pruning (%)", color=INK2)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="lower left")
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def md_table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + [
        "| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def judge_cost(r: dict, mode: str) -> str:
    return f"{f(r['judge_neurons']):,.1f} n" if mode == "real" else f"${f(r['jev_cost_usd']):.4f}"


def aggregate(rows: list[dict], sessions: list[str], mode: str, methods: list[str], tag: str = "") -> list[list]:
    agg = []
    for m in methods:
        rs = [r for r in rows if r["method"] == m and r["session"] in sessions]
        if not rs:
            continue
        n = max(1, len(rs))
        agg.append([f"{LABEL[m]}{tag} ({mode})",
                    f"{sum(f(r['pct_saved']) for r in rs) / n:.1f}%",
                    f"{100 * sum(f(r['needed_kept']) for r in rs) / max(1, sum(f(r['needed_items']) for r in rs)):.1f}%",
                    int(sum(f(r["user_messages_lost"]) for r in rs)),
                    "n/a" if m != "hybrid" else int(sum(f(r["invented_lines_removed"]) for r in rs)),
                    f"{sum(f(r['latency_ms']) for r in rs) / n / 1000:.1f} s",
                    (f"{sum(f(r['judge_neurons']) for r in rs) / n:,.1f}" if mode == "real"
                     else f"${sum(f(r['jev_cost_usd']) for r in rs) / n:.4f}"),
                    f"{sum(f(r['cf_neurons']) for r in rs) / n:,.0f}",
                    sum(r["status"] == "Fell back" for r in rs)])
    return agg


AGG_HEADER = ["Method", "Tokens saved", "Needed items kept", "User msgs lost", "Invented lines removed",
              "Latency", "Judge neurons", "Summary neurons", "Fell back"]


def latency_section() -> list[str]:
    p = EVAL / "first_call_latency_real.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text())
    out = ["", "### First-call latency (real)", "", d["note"], ""]
    out += md_table(["Session", "Method", "Wall time", "Result"],
                    [[r["session"], LABEL[r["method"]], f"{r['latency_s']:.1f} s", r["result"]] for r in d["rows"]])
    out += ["", "The *Latency* column in the tables above is ~0 s for the judge methods and for cached summaries "
                "because the replies come from the cache; use this table for timing."]
    return out


def mode_section(mode: str) -> list[str]:
    suffix = "" if mode == "real" else "_mock"
    all_rows = read(EVAL / f"results{suffix}.csv")
    title = "Main results (real)" if mode == "real" else "Secondary results (mock)"
    out = [f"## {title} — {mode_title(mode)}", ""]
    if not all_rows:
        return out + ["Not run yet.", ""]
    m = meta(mode)
    if m:
        out += [f"Run on {m['date']} · judge: **{m['judge']}** · summarizer: {m['summarizer']} · "
                f"budget {m['budget']:,} tokens · compaction point: {m.get('compaction_point', 'end of session')}.", ""]
        if mode == "real":
            out += [f"Cloudflare neurons on UTC day {m.get('neurons_utc_day', m['date'])}: "
                    f"{m.get('neurons_spent_today', 0):,.0f} of the 10,000 free (stop limit 9,000). "
                    + m.get("neurons_note", ""), ""]
    rows = default_rows(all_rows)
    over = sorted({r["session"] for r in rows if int(r["tokens_before"]) > BUDGET})
    judge_hdr = AGG_HEADER if mode == "real" else [h if h != "Judge neurons" else "Jev cost (mock estimate)" for h in AGG_HEADER]
    out += [f"### Averages over the {len(over)} sessions above the 120k budget — default thresholds 0.50 / 0.10 "
            f"({short_title(mode)})", ""]
    out += md_table(judge_hdr, aggregate(rows, over, mode, METHODS))
    failed = [r for r in rows if r["method"] == "plain" and "Summarizer failed" in r.get("warnings", "")]
    if failed:
        names = ", ".join(r["session"] for r in failed)
        ok_sessions = [x for x in over if x not in {r["session"] for r in failed}]
        out += ["", f"**Note:** the plain summary failed on {names} (GLM-4.7-flash returned an empty reply three "
                    "times: its reasoning used the whole output budget, even at 4,096 tokens). That session was "
                    "left unsummarized, so its plain row counts 0% saved and every item kept, which flatters plain's "
                    f"'needed items kept'. Averages over the other {len(ok_sessions)} sessions:", ""]
        out += md_table(judge_hdr, aggregate(rows, ok_sessions, mode, METHODS, " · excl. failed summary"))
    if mode == "real":
        out += latency_section()

    tuned_rows = [r for r in all_rows if r.get("thresholds") == "tuned"]
    tuned = m.get("tuned_thresholds")
    out += ["", f"### Default vs tuned thresholds ({short_title(mode)})", ""]
    if tuned_rows:
        out += md_table(judge_hdr, aggregate(rows, over, mode, ["prune_only", "hybrid"], " · default 0.50/0.10") +
                        aggregate(tuned_rows, over, mode, ["prune_only", "hybrid"], f" · tuned {tuned[0]}/{tuned[1]}"))
    elif tuned:
        est = m.get("tuned_sweep_estimate") or {}
        same = tuned == m.get("default_thresholds")
        out += [f"Tuned thresholds from the sweep: keep {tuned[0]} / drop {tuned[1]}"
                + (" — the same as the default, so the tuned results equal the default ones." if same else
                   f" (sweep estimate over the recorded scores: {est.get('needed_kept_pct')}% of needed items kept, "
                   f"{est.get('tool_tokens_saved_pct')}% of tool-output tokens saved)."),
                "",
                "**The full re-run with the tuned thresholds (phase B) was skipped** to stay within the day's free "
                "Cloudflare neurons; the tuned figures above come from re-classifying the recorded judge scores "
                "(the threshold sweep), which needs no new calls." if m.get("tuned_run_skipped") else ""]
    out += ["", f"### Per session ({short_title(mode)})", ""]
    per = [[r["session"], f"{LABEL[r['method']]} ({mode})", r.get("thresholds", "default"), r["status"],
            f"{int(r['tokens_before']):,}", f"{int(r['tokens_after']):,}", f"{r['pct_saved']}%",
            f"{r['needed_kept']}/{r['needed_items']}", r["needed_truncated"], r["needed_removed"],
            r["user_messages_lost"], r["invented_lines_removed"], f"{f(r['latency_ms']) / 1000:.1f} s",
            judge_cost(r, mode), f"{f(r['cf_neurons']):,.0f}"] for r in all_rows]
    out += md_table(["Session", "Method", "Thresholds", "Status", "Tokens before", "Tokens after", "Saved",
                     "Needed kept", "Needed cut", "Needed removed", "User msgs lost", "Invented removed", "Latency",
                     "Judge cost", "Summary neurons"], per)
    warns = [r for r in all_rows if r.get("warnings")]
    if warns:
        out += ["", "Warnings: " + "; ".join(f"{r['session']} / {LABEL[r['method']]}: {r['warnings']}" for r in warns)]
    falls = [r for r in all_rows if r["fallback_reason"]]
    if falls:
        out += ["", "Fallbacks: " + "; ".join(f"{r['session']} / {LABEL[r['method']]}: {r['fallback_reason']}" for r in falls)]

    clips = read(EVAL / f"clipping{suffix}.csv")
    if clips:
        out += ["", f"### Clipping trade-off — prune only, default thresholds ({short_title(mode)})", ""]
        tab = []
        for c in ["300", "1000", "unclipped"]:
            rs = [r for r in clips if r["clip"] == c and r["status"] != "Under budget"]
            if not rs:
                continue
            n = len(rs)
            tab.append([c, f"{sum(f(r['needed_kept_pct']) for r in rs) / n:.1f}%", f"{sum(f(r['pct_saved']) for r in rs) / n:.1f}%",
                        f"{sum(f(r['judge_requests']) for r in rs) / n:.1f}",
                        f"{sum(f(r['judge_input_tokens']) for r in rs) / n:,.0f}",
                        (f"{sum(f(r['judge_neurons']) for r in rs) / n:,.1f} neurons" if mode == "real"
                         else f"${sum(f(r['jev_cost_usd']) for r in rs) / n:.4f}"),
                        f"{sum(f(r['scoring_latency_ms']) for r in rs) / n / 1000:.1f} s"])
        out += md_table(["jev_item_max_tokens", "Needed kept (mean)", "Tokens saved", "Judge requests",
                         "Judge input tokens", "Judge cost", "Scoring latency"], tab)
        if m.get("unclipped_dropped"):
            out += ["", "**The unclipped run (phase D) was skipped** to stay within the day's free Cloudflare "
                        "neurons (planned cost ~730 neurons). It is not too expensive in itself; it can be run "
                        "with `python eval/run_eval.py --mode real` on a later UTC day (cached parts cost nothing)."]
    sweep = read(EVAL / f"threshold_sweep{suffix}.csv")
    if sweep:
        out += ["", f"### Threshold sweep — recorded prune-only scores re-classified, no extra calls ({short_title(mode)})", ""]
        balanced = [r for r in sweep if r["preset"] == "balanced"]
        presets = [r for r in sweep if r["preset"] and r["preset"] != "balanced"]
        tuned_r = [r for r in sweep if tuned and (f(r["keep"]), f(r["drop"])) == tuple(tuned)]
        rows_t = ([["default (balanced)", *[r[k] for k in ("keep", "drop")], f"{r['needed_kept_pct']}%",
                    f"{r['tool_tokens_saved_pct']}%"] for r in balanced] +
                  [[r["preset"], r["keep"], r["drop"], f"{r['needed_kept_pct']}%", f"{r['tool_tokens_saved_pct']}%"]
                   for r in presets] +
                  [["tuned (picked by the sweep)", r["keep"], r["drop"], f"{r['needed_kept_pct']}%",
                    f"{r['tool_tokens_saved_pct']}%"] for r in tuned_r])
        out += md_table(["Setting", "Keep", "Drop", "Needed kept", "Tool tokens saved"], rows_t)
        best_kept = max(f(r["needed_kept_pct"]) for r in sweep)
        out += ["", "Rule for *tuned*: the most tool-output tokens saved with ≥ 95% of needed items kept; if no "
                    "setting reaches 95%, the most needed items kept (ties: closest to the default). "
                    f"Best needed-kept anywhere on the grid: {best_kept:.1f}%. Full grid: `eval/threshold_sweep{suffix}.csv`."]
        if all(f(r["needed_kept_pct"]) == f(sweep[0]["needed_kept_pct"]) for r in sweep):
            out += ["", "Every grid point keeps the same share of needed items: the judge's scores are effectively "
                        "binary (0 or 1), so moving the thresholds only changes whether 0-scored items are cut or "
                        "dropped, never whether they are kept verbatim."]
        loso = read(EVAL / f"threshold_loso{suffix}.csv")
        if loso:
            out += ["", f"**Leave-one-session-out check** — thresholds tuned on the other sessions, applied to the "
                        f"held-out one ({short_title(mode)}):", ""]
            out += md_table(["Held-out session", "Tuned keep/drop", "Needed kept (tuned)", "Tool tokens saved (tuned)",
                             "Needed kept (default)", "Tool tokens saved (default)"],
                            [[r["held_out"], f"{r['keep']}/{r['drop']}", f"{r['needed_kept_pct']}%",
                              f"{r['tool_tokens_saved_pct']}%", f"{r['default_needed_kept_pct']}%",
                              f"{r['default_tool_tokens_saved_pct']}%"] for r in loso])
    out += ["", f"Figures: `docs/figures/tokens_saved_{mode}.png`, `needed_kept_{mode}.png`, "
                f"`clipping_{mode}.png`, `threshold_sweep_{mode}.png`.", ""]
    return out


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    real_judge = meta("real").get("judge", "Cloudflare judge, standing in for Jev")
    md = ["# Evaluation results", "",
          "Four methods on every sample in `data/samples/`: FIFO sliding window, plain summary only, prune only "
          "(judge), and the full JevCompact hybrid. Real and mock runs are reported separately and never combined.", "",
          f"**Judge.** Paid Jev is not used. The real run's judge is the **{real_judge}**: a Workers AI chat model asked "
          "Jev's yes/no questions and returning strict JSON scores (see PROGRESS.md, design deviations). Its scores are "
          "not calibrated like Jev's, so results are shown at the default thresholds and at thresholds tuned by the sweep.", "",
          "**Compaction point.** Each session is compacted just before the agent's final \"done\" answer (the one "
          "closing assistant message is left out for every method), because compaction fires mid-task and a judge "
          "asked what is \"still needed to finish the task\" after it is finished answers \"nothing\".", "",
          "**Metrics.** *Needed items kept*: hand-labelled needed tool results (`eval/LABELS.md`) still present "
          "word for word in the compacted session (pinned or kept; truncated, dropped or summarized do not count). "
          "*Invented lines removed*: summary lines the judge's check found no source for (hybrid only). *Judge neurons*: "
          "Cloudflare cost of the judge requests (first generation; replies are cached, so a re-run costs nothing; the "
          "hybrid's prune step reuses the prune-only replies). *Summary neurons*: Cloudflare cost of the summary. "
          "Mock tables show the Jev cost estimate from tiktoken counts instead.", ""]
    for mode in ("real", "mock"):
        md += mode_section(mode)
        suffix = "" if mode == "real" else "_mock"
        rows = default_rows(read(EVAL / f"results{suffix}.csv"))
        if rows:
            grouped_bars(rows, "pct_saved", "Tokens saved (%)",
                         f"Tokens saved by method, default thresholds ({short_title(mode)})",
                         FIG / f"tokens_saved_{mode}.png", 100)
            grouped_bars(rows, "needed_kept_pct", "Needed items kept verbatim (%)",
                         f"Hand-labelled needed items kept, default thresholds ({short_title(mode)})",
                         FIG / f"needed_kept_{mode}.png", 110)
        clipping_chart(read(EVAL / f"clipping{suffix}.csv"), mode, FIG / f"clipping_{mode}.png")
        t = meta(mode).get("tuned_thresholds")
        sweep_chart(read(EVAL / f"threshold_sweep{suffix}.csv"), mode, FIG / f"threshold_sweep_{mode}.png",
                    tuple(t) if t else None)
    (EVAL / "results.md").write_text("\n".join(md) + "\n")
    print("wrote eval/results.md and docs/figures/")


if __name__ == "__main__":
    main()
