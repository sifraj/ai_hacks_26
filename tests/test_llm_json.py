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
