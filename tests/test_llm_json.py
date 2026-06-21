from src.agents.llm_json import strip_json_fences


def test_plain_json_passes_through():
    assert strip_json_fences('{"a": 1}') == '{"a": 1}'


def test_strips_json_language_tagged_fence():
    raw = '```json\n{"a": 1}\n```'
    assert strip_json_fences(raw) == '{"a": 1}'


def test_strips_bare_fence_no_language_tag():
    raw = '```\n{"a": 1}\n```'
    assert strip_json_fences(raw) == '{"a": 1}'


def test_strips_surrounding_whitespace_and_fence():
    raw = '  \n```json\n{"a": 1}\n```\n  '
    assert strip_json_fences(raw) == '{"a": 1}'


def test_multiline_json_inside_fence():
    raw = '```json\n{\n  "a": 1,\n  "b": 2\n}\n```'
    assert strip_json_fences(raw) == '{\n  "a": 1,\n  "b": 2\n}'


def test_no_fence_just_strips_whitespace():
    assert strip_json_fences('  {"a": 1}  ') == '{"a": 1}'


def test_discards_trailing_prose_after_fenced_empty_array():
    raw = (
        '```json\n[]\n```\n\n'
        '**Internal rationale (not part of output):**\n\n'
        '- BNB-USD: no corroboration, no trade proposed.'
    )
    assert strip_json_fences(raw) == "[]"


def test_discards_trailing_prose_after_fenced_nonempty_array():
    raw = (
        '```json\n[{"asset": "BTC-USD", "side": "BUY"}]\n```\n\n'
        'Note: only one trade proposed due to thin corroboration.'
    )
    assert strip_json_fences(raw) == '[{"asset": "BTC-USD", "side": "BUY"}]'


def test_discards_trailing_prose_with_no_fence_at_all():
    raw = '[]\n\nNo trades proposed because signals are too weak.'
    assert strip_json_fences(raw) == "[]"


def test_malformed_json_returns_candidate_unchanged_for_caller_to_error_on():
    raw = "not json at all"
    assert strip_json_fences(raw) == "not json at all"


def test_discards_leading_prose_before_unfenced_json():
    raw = (
        "I only have 2 distinct signal_ids in this batch, fewer than the "
        "required 3. I will note this constraint.\n\n"
        '{"tick_id": "t1", "regime": "RANGING"}'
    )
    assert strip_json_fences(raw) == '{"tick_id": "t1", "regime": "RANGING"}'


def test_discards_leading_and_trailing_prose_combined():
    raw = (
        "Here is my analysis before the output.\n\n"
        '```json\n{"a": 1}\n```\n\n'
        "And here is a closing note."
    )
    assert strip_json_fences(raw) == '{"a": 1}'
