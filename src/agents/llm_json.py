from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def strip_json_fences(text: str) -> str:
    """Extract a JSON value from an LLM response that may be wrapped in markdown
    code fences and/or surrounded by leading/trailing prose, despite being told
    to return JSON only. Scans for the first valid JSON value (object or array)
    starting at any '{' or '[' in the text and returns just that slice, so any
    commentary before or after it is discarded rather than breaking parsing."""
    stripped = text.strip()

    fence_match = _FENCE_RE.search(stripped)
    candidate = fence_match.group(1).strip() if fence_match else stripped

    decoder = json.JSONDecoder()
    for i, ch in enumerate(candidate):
        if ch not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(candidate, i)
            return candidate[i:end]
        except json.JSONDecodeError:
            continue

    return candidate
