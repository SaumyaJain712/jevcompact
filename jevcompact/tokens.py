"""Token counting with tiktoken (cl100k_base), falling back to len/4 offline."""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _encoding():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - only when the encoding can't load
        return None


@lru_cache(maxsize=8192)
def count_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _encoding()
    if enc is None:  # pragma: no cover
        return max(1, len(text) // 4)
    return len(enc.encode(text, disallowed_special=()))


def clip_to_tokens(text: str, max_tokens: int, marker: str = "\n[…]\n") -> str:
    """Keep the head (3/4) and tail (1/4) of text so it fits in max_tokens."""
    total = count_tokens(text)
    if total <= max_tokens:
        return text
    budget = max(1, max_tokens - count_tokens(marker))
    ratio = len(text) / total
    chars = int(budget * ratio * 0.95)
    while chars > 0:
        head = text[: int(chars * 0.75)]
        tail = text[len(text) - (chars - len(head)):] if chars - len(head) > 0 else ""
        clipped = head + marker + tail
        if count_tokens(clipped) <= max_tokens:
            return clipped
        chars = int(chars * 0.9)
    return text[: max_tokens]
