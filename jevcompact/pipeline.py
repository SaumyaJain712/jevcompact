"""Compaction pipeline: Pin -> Prune -> Summarize -> Check -> Fall back."""
from __future__ import annotations

import asyncio
import copy
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from .batching import JudgeFailure
from .check import check_summary
from .config import CompactionConfig
from .formats import SUMMARY_HEADER, parse_session, render, set_item_content, total_tokens, user_messages_lost
from .judges import Judge, build_judge
from .models import CompactionResult, Decision, Session, SummaryInfo
from .pinning import apply_pins
from .prune import classify, drop_stub, score_items, truncate
from .ratelimit import RateLimiter
from .recall import RecallStore, default_store, recall
from .summarize import build_request, select_groups, sources_for
from .summarizers import Summarizer, SummarizerError, build_summarizer
from .tokens import count_tokens

Method = Literal["hybrid", "prune_only", "plain"]


class CompactionError(RuntimeError):
    pass


class _Run:
    def __init__(self, session: Session, config: CompactionConfig, judge: Judge, summarizer: Summarizer,
                 store: RecallStore, run_id: str):
        self.session, self.config, self.judge, self.summarizer, self.store = session, config, judge, summarizer, store
        self.run_id = run_id
        self.t0 = time.perf_counter()
        self.limiter = RateLimiter(config.jev_requests_per_s, config.jev_tokens_per_s)
        self.jev_requests = 0
        self.jev_tokens = 0
        self.scoring_ms = 0.0
        self.warnings: list[str] = []

    def item_id(self, idx: int) -> str:
        return f"{self.run_id}-{idx}"

    def pinned_or(self, it, score, action, reason, tokens_after) -> Decision:
        if it.pinned:
            return Decision(self.item_id(it.index), it.index, it.msg_index, it.block_index, it.role, it.title,
                            None, "Pinned", it.pin_reason, it.tokens, it.tokens, tool_call_id=it.tool_call_id)
        return Decision(self.item_id(it.index), it.index, it.msg_index, it.block_index, it.role, it.title,
                        score, action, reason, it.tokens, tokens_after, tool_call_id=it.tool_call_id)

    def unscored_decisions(self, reason: str) -> list[Decision]:
        return [self.pinned_or(it, None, "Kept", reason, it.tokens) for it in self.session.items]

    def finish(self, status, decisions, replacements, removed, summary: SummaryInfo | None,
               fallback_reason=None) -> CompactionResult:
        s = self.session
        summary_text = None
        if summary is not None:
            summary_text = "\n".join([SUMMARY_HEADER.format(n=summary.summarized_messages), *summary.lines_kept])
        out, index_map = render(s, replacements, removed, summary_text)
        for d in decisions:
            if s.items[d.item_index].group in removed:
                d.summarized, d.tokens_after = True, 0
                d.reason = f"{d.reason} · then summarized" if d.reason else "summarized"
        lost = user_messages_lost(s.messages, out)
        if lost:  # never expected; pinned groups are never removed
            self.warnings.append(f"{lost} user messages missing from output")
        tokens_after = total_tokens(out)
        if status == "Compacted" and tokens_after > self.config.budget:
            self.warnings.append("Still over budget: pinned content alone exceeds the budget.")
        return CompactionResult(
            run_id=self.run_id, status=status, format=s.format, messages=out,
            tokens_before=s.tokens, tokens_after=tokens_after, decisions=decisions, summary=summary,
            judge=self.judge.name, summarizer=self.summarizer.name,
            jev_requests=self.jev_requests, jev_input_tokens=self.jev_tokens,
            jev_cost_usd=round(self.jev_tokens * self.config.jev_price_per_m_input / 1e6, 6),
            summarizer_neurons=summary.neurons if summary else 0.0,
            latency_ms=round((time.perf_counter() - self.t0) * 1000, 1),
            scoring_latency_ms=round(self.scoring_ms, 1), fallback_reason=fallback_reason,
            warnings=self.warnings, user_messages_lost=lost, index_map=index_map,
            config=self.config.public_dict(),
        )

    async def plain_summary(self, status, reason: str | None) -> CompactionResult:
        """The plain summary path: pins respected, oldest turns summarized, no Jev."""
        s, cfg = self.session, self.config
        decisions = self.unscored_decisions(f"{status}: not scored" if reason else "not scored (plain summary)")
        groups = select_groups(s, s.msg_tokens, cfg.budget, cfg.summary_reserve_tokens)
        summary = None
        if groups:
            try:
                sres = await self.summarizer.summarize(build_request(s, groups, {}))
                lines = [ln for ln in sres.text.splitlines() if ln.strip()]
                summary = SummaryInfo(sres.text, lines, [], [(ln, None) for ln in lines],
                                      sum(len(g.msg_indices) for g in groups), sres.neurons, False, sres.cached)
            except SummarizerError as exc:
                self.warnings.append(f"Summarizer failed, session left unsummarized: {exc}")
        removed = {g.index for g in groups} if summary else set()
        return self.finish(status, decisions, {}, removed, summary, reason)

    async def fallback(self, reason: str) -> CompactionResult:
        if not self.config.fallback_enabled:
            raise CompactionError(reason)
        return await self.plain_summary("Fell back", reason)


async def compact(messages: Any, config: CompactionConfig | None = None, *, judge: Judge | None = None,
                  summarizer: Summarizer | None = None, recall_store: RecallStore | None = None,
                  run_id: str | None = None, method: Method = "hybrid") -> CompactionResult:
    """Compact a session (OpenAI or Anthropic message array). Output uses the input format.

    `method` exists for the evaluation baselines: "prune_only" skips the
    summary, "plain" is the plain summary path with no Jev.
    """
    config = config or CompactionConfig.from_env()
    session = parse_session(messages)
    run = _Run(session, config, judge or build_judge(config), summarizer or build_summarizer(config),
               recall_store or default_store(), run_id or uuid.uuid4().hex[:12])
    apply_pins(session, config)

    if session.tokens <= config.budget:  # FR2: only compact past the budget
        return run.finish("Under budget", run.unscored_decisions("Under budget: not scored"), {}, set(), None)
    if method == "plain":
        return await run.plain_summary("Compacted", None)

    # Step 2: Prune
    try:
        scored = await score_items(session, config, run.judge, run.limiter)
    except JudgeFailure as exc:
        return await run.fallback(str(exc))
    run.jev_requests += scored.requests
    run.jev_tokens += scored.input_tokens
    run.scoring_ms = scored.latency_ms

    decisions: list[Decision] = []
    replacements: dict[int, str] = {}
    msg_tokens_now = list(session.msg_tokens)
    for it in session.items:
        if it.pinned:
            decisions.append(run.pinned_or(it, None, "Pinned", "", it.tokens))
            continue
        if it.index in scored.skipped:
            decisions.append(run.pinned_or(it, None, "Kept", scored.skipped[it.index], it.tokens))
            continue
        if it.index not in scored.scores:  # an unpinned USER item cannot happen; defensive
            decisions.append(run.pinned_or(it, None, "Kept", "not scored", it.tokens))
            continue
        score = scored.scores[it.index]
        action = classify(score, config)
        iid = run.item_id(it.index)
        new_text = None
        if action == "Dropped":
            new_text = drop_stub(it, score, iid)
            reason = f"score {score:.2f} < drop {config.drop_threshold:.2f}"
        elif action == "Cut":
            new_text = truncate(it.text, config, iid)
            reason = f"unsure ({config.drop_threshold:.2f} ≤ {score:.2f} < {config.keep_threshold:.2f}): truncated"
        else:
            reason = (f"score {score:.2f} ≥ keep {config.keep_threshold:.2f}" if score >= config.keep_threshold
                      else "unsure: kept verbatim (keep_when_unsure)")
        tokens_after = it.tokens
        if new_text is not None and new_text != it.text:
            run.store.put(iid, run.run_id, it.text)
            replacements[it.index] = new_text
            tokens_after = count_tokens(new_text)
            msg_tokens_now[it.msg_index] += tokens_after - it.tokens
        decisions.append(run.pinned_or(it, score, action, reason, tokens_after))

    before = session.tokens
    after_prune = sum(msg_tokens_now)
    saved = (before - after_prune) / before
    if after_prune > config.budget and saved < config.min_savings and method == "hybrid":
        return await run.fallback(f"Jev saved only {saved:.0%} (minimum {config.min_savings:.0%})")
    if after_prune <= config.budget or method == "prune_only":
        return run.finish("Compacted", decisions, replacements, set(), None)

    # Step 3: Summarize the oldest unpinned remainder
    groups = select_groups(session, msg_tokens_now, config.budget, config.summary_reserve_tokens)
    if not groups:
        return run.finish("Compacted", decisions, replacements, set(), None)
    try:
        sres = await run.summarizer.summarize(build_request(session, groups, replacements))
    except SummarizerError as exc:
        run.warnings.append(f"Summarizer failed, kept the pruned session unsummarized: {exc}")
        return run.finish("Compacted", decisions, replacements, set(), None)

    # Step 4: Check each summary line against the tool outputs
    try:
        chk = await check_summary(sres.text, sources_for(session, groups), config, run.judge, run.limiter)
    except JudgeFailure as exc:
        return await run.fallback(f"Summary check failed: {exc}")
    run.jev_requests += chk.requests
    run.jev_tokens += chk.input_tokens
    summary = SummaryInfo(sres.text, chk.kept, chk.removed, chk.line_scores,
                          sum(len(g.msg_indices) for g in groups), sres.neurons, True, sres.cached)
    return run.finish("Compacted", decisions, replacements, {g.index for g in groups}, summary)


def compact_sync(messages: Any, config: CompactionConfig | None = None, **kwargs) -> CompactionResult:
    """Blocking wrapper around compact(); safe to call from inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(compact(messages, config, **kwargs))
    with ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, compact(messages, config, **kwargs)).result()


def restore_item(result: CompactionResult, item_id: str, store: RecallStore | None = None) -> list[dict]:
    """Return a copy of result.messages with one dropped/cut item put back verbatim."""
    d = next((d for d in result.decisions if d.item_id == item_id), None)
    if d is None:
        raise KeyError(f"No decision with item id {item_id!r}")
    full = recall(item_id, store)
    out_index = result.index_map[d.message_index]
    if out_index is None:
        raise ValueError("This item was folded into the summary; use recall() to read it.")
    out = copy.deepcopy(result.messages)
    set_item_content(out[out_index], d.block_index, full)
    return out
