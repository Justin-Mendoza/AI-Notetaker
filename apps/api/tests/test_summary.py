import uuid
from types import SimpleNamespace

import pytest

from app.services.summarization import (
    MAX_SLICE_CHARS,
    OpenAISummarizer,
    SummaryContent,
    SummaryError,
    SummarySegment,
    validate_summary,
)


def empty_notes():
    return {
        "overview": "The meeting covered planning.",
        "key_points": ["Planning was discussed."],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
    }


def test_empty_decisions_and_actions_are_valid():
    result = validate_summary(empty_notes(), set())
    assert result.topics == []  # Old saved summaries still load.
    assert result.decisions == []
    assert result.action_items == []


def test_class_topic_explanation_requires_saved_segment_evidence():
    segment_id = uuid.uuid4()
    topic = {
        "heading": "Photosynthesis",
        "summary": "The class explained how plants convert light into chemical energy.",
        "key_details": ["Chlorophyll absorbs light."],
        "evidence_segment_ids": [str(segment_id)],
    }
    result = validate_summary(empty_notes() | {"topics": [topic]}, {segment_id})
    assert result.topics[0].heading == "Photosynthesis"
    with pytest.raises(SummaryError) as error:
        validate_summary(empty_notes() | {"topics": [topic]}, set())
    assert error.value.code == "SUMMARY_EVIDENCE_INVALID"


def test_malformed_output_and_unknown_evidence_are_rejected():
    with pytest.raises(SummaryError) as missing:
        validate_summary({"overview": "Only one field"}, set())
    assert missing.value.code == "SUMMARY_INVALID"
    payload = empty_notes() | {
        "decisions": [{"text": "Proceed", "evidence_segment_ids": [str(uuid.uuid4())]}]
    }
    with pytest.raises(SummaryError) as evidence:
        validate_summary(payload, set())
    assert evidence.value.code == "SUMMARY_EVIDENCE_INVALID"


def test_response_refusal_and_invalid_json_are_retryable():
    summarizer = OpenAISummarizer.__new__(OpenAISummarizer)
    summarizer.model = "fake-model"
    summarizer.client = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                status="completed", output=[], output_text="not-json"
            )
        )
    )
    with pytest.raises(SummaryError) as error:
        summarizer._request("untrusted text", set(), "instructions")
    assert error.value.code == "SUMMARY_INVALID"


def test_summary_rechecks_deletion_before_each_provider_request():
    summarizer = OpenAISummarizer.__new__(OpenAISummarizer)
    summarizer.model = "fake-model"
    calls = []
    summarizer.client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs))
    )

    def cancelled():
        raise RuntimeError("meeting deleted")

    summarizer.check_active = cancelled
    with pytest.raises(RuntimeError, match="meeting deleted"):
        summarizer._request("untrusted text", set(), "instructions")
    assert calls == []


def test_long_transcript_uses_chronological_slices_then_synthesis():
    class StubSummarizer(OpenAISummarizer):
        def __init__(self):
            self.model = "fake-model"
            self.calls = []

        def _request(self, body, allowed_ids, instructions):
            self.calls.append((body, allowed_ids))
            return SummaryContent.model_validate(empty_notes())

    summarizer = StubSummarizer()
    first = SummarySegment(uuid.uuid4(), 0, 1000, "A" * MAX_SLICE_CHARS)
    second = SummarySegment(uuid.uuid4(), 1000, 2000, "B" * MAX_SLICE_CHARS)
    result = summarizer.summarize([first, second])
    assert result.decisions == []
    assert len(summarizer.calls) >= 3
    assert "A" in summarizer.calls[0][0]
    assert "B" in summarizer.calls[-2][0]
    assert summarizer.calls[-1][1] == {first.id, second.id}
