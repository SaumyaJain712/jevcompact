"""Step 1, Pin: the task, every user message, the latest turn and error output."""
from __future__ import annotations

from .config import CompactionConfig
from .models import Session


def apply_pins(session: Session, config: CompactionConfig) -> None:
    task_set = False
    for it in session.items:
        if it.role == "USER":
            it.pinned = True
            if not task_set:
                it.is_task, it.pin_reason, task_set = True, "task (first user message)", True
            else:
                it.pin_reason = "user message"
        elif it.role == "ERROR":  # config.pin_errors is locked to True
            it.pinned, it.pin_reason = True, "error output"

    turns = [g for g in session.groups if g.kind == "turn" and g.items]
    for g in turns[-config.pin_last_turns:]:
        for idx in g.items:
            it = session.items[idx]
            if not it.pinned:
                it.pinned, it.pin_reason = True, "latest turn"
