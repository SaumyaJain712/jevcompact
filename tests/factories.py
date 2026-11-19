"""Build synthetic agent sessions in OpenAI or Anthropic format for tests."""
from __future__ import annotations

import json
from dataclasses import dataclass

from jevcompact.tokens import count_tokens

TASK = "Fix the checkout total bug in src/cart.ts so that `npm test` passes."


def filler(n_tokens: int, tag: str = "x") -> str:
    """Distinct (non-repeating) text of roughly n_tokens tokens."""
    lines, total, i = [], 0, 0
    while total < n_tokens:
        line = f"{tag}/module_{i}.ts:{i + 1}: export const value_{tag}_{i} = compute({i}, '{tag}');"
        lines.append(line)
        total += count_tokens(line) + 1
        i += 1
    return "\n".join(lines)


@dataclass
class Step:
    command: str
    output: str
    is_error: bool = False
    user_after: str | None = None  # a user message following this step


def build(steps: list[Step], fmt: str = "openai", task: str = TASK, system: str | None = "You are a coding agent.",
          final_text: str | None = "Done: the total is now computed from item prices.") -> list[dict]:
    msgs: list[dict] = []
    if system and fmt == "openai":
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": task})
    for i, s in enumerate(steps):
        cid = f"call_{i}"
        if fmt == "openai":
            msgs.append({"role": "assistant", "content": f"Step {i}: running {s.command}",
                         "tool_calls": [{"id": cid, "type": "function",
                                         "function": {"name": "bash", "arguments": json.dumps({"command": s.command})}}]})
            msgs.append({"role": "tool", "tool_call_id": cid, "content": s.output})
            if s.user_after:
                msgs.append({"role": "user", "content": s.user_after})
        else:
            msgs.append({"role": "assistant", "content": [
                {"type": "text", "text": f"Step {i}: running {s.command}"},
                {"type": "tool_use", "id": cid, "name": "bash", "input": {"command": s.command}}]})
            block = {"type": "tool_result", "tool_use_id": cid, "content": s.output}
            if s.is_error:
                block["is_error"] = True
            content = [block]
            if s.user_after:
                msgs.append({"role": "user", "content": content})
                msgs.append({"role": "assistant", "content": [{"type": "text", "text": "Noted."}]})
                msgs.append({"role": "user", "content": [{"type": "text", "text": s.user_after}]})
            else:
                msgs.append({"role": "user", "content": content})
    if final_text:
        if fmt == "openai":
            msgs.append({"role": "assistant", "content": final_text})
        else:
            msgs.append({"role": "assistant", "content": [{"type": "text", "text": final_text}]})
    return msgs


def checkout_session(fmt: str = "openai", scale: int = 1500) -> list[dict]:
    """A small checkout-bugfix style session with a mix of item kinds."""
    steps = [
        Step("ls node_modules", "\n".join(f"package-{i}" for i in range(scale // 2))),
        Step("cat src/cart.ts", "export function cartTotal(items) {\n  let total;\n  for (const i of items) total += i.price;\n"
                                "  return total;\n}\n" + filler(scale, "cart")),
        Step("grep -rn price src/", "src/cart.ts:3: total += i.price\n" + filler(scale, "grep")),
        Step("cat package-lock.json", filler(scale * 2, "lock")),
        Step("npm test", "FAIL src/cart.test.ts\n  TypeError: total is undefined (cart.ts:88)\n" + filler(200, "jest"),
             is_error=True, user_after="Please don't change the public API."),
        Step("cat README.md", filler(scale, "readme")),
        Step("git log --oneline -n 50", filler(scale, "git")),
        Step("cat src/cart.ts", "export function cartTotal(items) {\n  let total = 0;\n" + filler(300, "cart2")),
        Step("npm test", "PASS src/cart.test.ts\nTests: 12 passed"),
    ]
    return build(steps, fmt)
