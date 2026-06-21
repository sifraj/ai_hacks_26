from __future__ import annotations

import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def strip_json_fences(text: str) -> str:
    """Claude sometimes wraps JSON output in markdown code fences despite
    being told not to. Strip them before attempting to parse the response."""
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped
