import pytest
from pydantic import ValidationError

from minirag.contracts import AskRequest, AskResponse, Citation, ErrorInfo, Usage


def test_question_strips_surrounding_whitespace() -> None:
    request = AskRequest(question="  hello  ")
    assert request.question == "hello"


def test_blank_question_is_rejected() -> None:
    for question in ("", "   ", "\n\t"):
        with pytest.raises(ValidationError):
            AskRequest(question=question)


def test_question_length_limits_apply_after_strip() -> None:
    AskRequest(question="a" * 2000)
    AskRequest(question="  " + "a" * 2000 + "  ")
    with pytest.raises(ValidationError):
        AskRequest(question="a" * 2001)


def test_top_k_defaults_to_5_and_rejects_out_of_range() -> None:
    assert AskRequest(question="hi").top_k == 5
    assert AskRequest(question="hi", top_k=1).top_k == 1
    assert AskRequest(question="hi", top_k=20).top_k == 20
    for top_k in (0, 21):
        with pytest.raises(ValidationError):
            AskRequest(question="hi", top_k=top_k)


def test_optional_ids_default_to_none() -> None:
    request = AskRequest(question="hi")
    assert request.session_id is None
    assert request.user_id is None


def test_error_is_required_only_when_status_is_error() -> None:
    error = ErrorInfo(code="invalid_request", message="问题无效")
    failed = _response(status="error", answer="问题无效", error=error)
    assert failed.error == error

    with pytest.raises(ValidationError):
        _response(status="error", answer="问题无效")

    for status in ("answered", "insufficient_evidence"):
        ok = _response(status=status, error=None)
        assert ok.error is None
        with pytest.raises(ValidationError):
            _response(status=status, error=error)


def test_unknown_error_code_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ErrorInfo(code="timeout", message="超时")


def test_citations_and_degraded_default_to_empty_lists() -> None:
    first = _response()
    second = _response()
    assert first.citations == []
    assert first.degraded == []
    first.citations.append(
        Citation(marker="1", chunk_id="doc#0", doc_id="doc", snippet="片段")
    )
    assert second.citations == []


def test_degraded_names_are_sorted() -> None:
    response = _response(degraded=["rerank", "cache"])
    assert response.degraded == ["cache", "rerank"]


def test_usage_may_be_none_and_zero_is_a_real_count() -> None:
    missing = _response()
    assert missing.usage is None

    present = _response(usage=Usage(model="demo", input_tokens=0, output_tokens=3))
    assert present.usage is not None
    assert present.usage.input_tokens == 0
    assert present.usage.output_tokens == 3


def test_citations_are_empty_unless_intent_is_knowledge() -> None:
    citation = Citation(marker="1", chunk_id="doc#0", doc_id="doc", snippet="片段")
    knowledge = _response(intent="knowledge", citations=[citation])
    assert knowledge.citations == [citation]
    for intent in (None, "chat", "calculate"):
        with pytest.raises(ValidationError):
            _response(intent=intent, citations=[citation])


def test_latency_and_token_counts_reject_negative_values() -> None:
    with pytest.raises(ValidationError):
        _response(latency_ms=-1)
    with pytest.raises(ValidationError):
        Usage(model="demo", input_tokens=-1, output_tokens=0)


def test_citation_scores_default_to_none() -> None:
    citation = Citation(marker="1", chunk_id="doc#0", doc_id="doc", snippet="片段")
    assert citation.heading is None
    assert citation.vector_score is None
    assert citation.bm25_score is None
    assert citation.rrf_score is None
    assert citation.rerank_score is None


def _response(**overrides: object) -> AskResponse:
    payload: dict[str, object] = {
        "request_id": "req-1",
        "session_id": "sess-1",
        "status": "answered",
        "answer": "回答",
        "latency_ms": 0,
    }
    payload.update(overrides)
    return AskResponse(**payload)  # type: ignore[arg-type]
