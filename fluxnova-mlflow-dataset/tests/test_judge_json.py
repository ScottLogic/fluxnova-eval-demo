from unittest.mock import Mock

import pytest

from fluxnova_mlflow_dataset import scorers


@pytest.mark.parametrize("content", [
    '{"score": 0.8, "rationale": "Evidence matches"}',
    '```json\n{"score": 0.8, "rationale": "Evidence matches"}\n```',
    '```\n{"score": 0.8, "rationale": "Evidence matches"}\n```',
])
def test_valid_bare_or_whole_fenced_json_is_parsed(content):
    assert scorers._parse_judge_json(content) == (0.8, "Evidence matches")


@pytest.mark.parametrize("content", [
    "not JSON", 'prose {"score": 1, "rationale": "OK"}', "[]",
    '{"score": true, "rationale": "OK"}', '{"score": "0.8", "rationale": "OK"}',
    '{"score": NaN, "rationale": "OK"}', '{"score": Infinity, "rationale": "OK"}',
    '{"score": 1.1, "rationale": "OK"}', '{"score": -0.1, "rationale": "OK"}',
    '{"score": 0.8}', '{"score": 0.8, "rationale": ""}',
])
def test_malformed_or_invalid_scores_still_fail(content):
    with pytest.raises(ValueError):
        scorers._parse_judge_json(content)


def test_openai_json_mode_and_reported_fence_preserve_golden_threshold(monkeypatch):
    import litellm

    completion = Mock(return_value={"choices": [{"message": {"content":
        '```json\n{"score": 0.8, "rationale": "Same decision and evidence"}\n```'}}]})
    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(scorers, "GOLDEN_MATCH_THRESHOLD", 0.7)
    raw = scorers._llm_judge("criteria", {}, model="openai/gpt-4o-mini")
    assert completion.call_args.kwargs["response_format"] == {"type": "json_object"}
    monkeypatch.setattr(scorers, "_llm_judge", Mock(return_value=raw))
    judged = scorers.matches_golden(outputs="REJECT", expectations={"expected_output": "REJECT"})
    assert judged.value == "yes" and judged.metadata["score"] == "0.8000"


def test_ollama_keeps_native_json_mode_and_invalid_content_fails_closed(monkeypatch):
    import litellm

    completion = Mock(return_value={"choices": [{"message": {"content": "invalid"}}]})
    monkeypatch.setattr(litellm, "completion", completion)
    judged = scorers._llm_judge("criteria", {}, model="ollama/gemma4:e2b")
    assert judged.value == 0.0 and "Could not parse" in judged.rationale
    assert completion.call_args.kwargs["format"] == "json"
