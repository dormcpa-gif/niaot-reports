"""Tests for the LLM-driven deep analysis service. The Anthropic client
itself is monkeypatched everywhere -- these tests validate our glue code
(text extraction, prompt assembly, JSON-block parsing, error handling),
never make a real network call, and never require a real API key."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import llm_analysis_service as svc


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeMessages:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.last_call_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return SimpleNamespace(content=[_FakeTextBlock(self._response_text)])


class _FakeAnthropicClient:
    def __init__(self, response_text: str) -> None:
        self.messages = _FakeMessages(response_text)


# ---- extract_text_from_upload ----


def test_extracts_plain_text_csv_content():
    text, note = svc.extract_text_from_upload("activity.csv", b"Date,Amount\n2025-01-01,100\n")
    assert note is None
    assert "Date,Amount" in text


def test_flags_empty_file():
    text, note = svc.extract_text_from_upload("empty.txt", b"")
    assert note == "הקובץ ריק."


def test_flags_undecodable_bytes():
    text, note = svc.extract_text_from_upload("weird.bin", b"\xff\xfe\x00\x01binary-garbage")
    assert note is not None
    assert text == ""


# ---- _parse_structured_json ----


def test_parses_valid_json_block():
    response = 'סיכום מילולי כלשהו.\n\n```json\n{"meta": {"tax_year": 2024}}\n```\n'
    structured, error = svc._parse_structured_json(response)
    assert error is None
    assert structured == {"meta": {"tax_year": 2024}}


def test_missing_json_block_is_flagged_not_silently_dropped():
    structured, error = svc._parse_structured_json("רק טקסט חופשי, בלי JSON כלל.")
    assert structured is None
    assert error is not None


def test_malformed_json_block_is_flagged():
    response = "```json\n{not valid json,,,}\n```"
    structured, error = svc._parse_structured_json(response)
    assert structured is None
    assert error is not None


# ---- run_deep_analysis ----


def test_raises_when_no_files_supplied():
    with pytest.raises(ValueError, match="לפחות מסמך אחד"):
        svc.run_deep_analysis("client-1", 2024, [])


def test_raises_when_no_document_yielded_readable_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Genuinely undecodable bytes (not valid UTF-8, and doesn't start with
    # the %PDF- signature) -- must fail extraction and short-circuit
    # before any call reaches the (real, unmocked) Anthropic client here.
    with pytest.raises(ValueError, match="לא ניתן היה לחלץ טקסט"):
        svc.run_deep_analysis("client-1", 2024, [("scan.pdf", b"\xff\xfe\x00\x01garbage")])


def test_raises_a_clear_error_when_api_key_is_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        svc.run_deep_analysis("client-1", 2024, [("form1040.txt", b"Form 1040 line 24: 0")])


def test_successful_run_returns_narrative_and_structured_result(monkeypatch):
    fake_response = (
        "הכרעות מקדימות: תושב ישראל.\n\n"
        '```json\n{"residency": {"israeli_resident": true, "confidence": "high"}}\n```'
    )
    fake_client = _FakeAnthropicClient(fake_response)
    monkeypatch.setattr(svc, "_get_client", lambda: fake_client)
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    result = svc.run_deep_analysis(
        "client-1", 2024, [("form1040.txt", b"Form 1040 line 24: 0")], client_context="לקוח לדוגמה"
    )

    assert result.client_id == "client-1"
    assert result.tax_year == 2024
    assert result.model == "claude-sonnet-5"
    assert "תושב ישראל" in result.narrative
    assert "```json" not in result.narrative
    assert result.structured == {"residency": {"israeli_resident": True, "confidence": "high"}}
    assert result.structured_parse_error is None
    assert len(result.input_documents) == 1
    assert result.input_documents[0].filename == "form1040.txt"

    # the system prompt and both the document text + extra context reached the model
    sent_system = fake_client.messages.last_call_kwargs["system"]
    sent_user = fake_client.messages.last_call_kwargs["messages"][0]["content"]
    assert "רואה חשבון ישראלי" in sent_system
    assert "form1040.txt" in sent_user
    assert "לקוח לדוגמה" in sent_user


def test_documents_with_no_extractable_text_are_still_sent_with_a_note(monkeypatch):
    fake_client = _FakeAnthropicClient("סיכום.\n```json\n{}\n```")
    monkeypatch.setattr(svc, "_get_client", lambda: fake_client)

    svc.run_deep_analysis(
        "client-1",
        2024,
        [("scan.pdf", b"\x00\x01"), ("good.txt", b"Form 1040 line 24: 0")],
    )

    sent_user = fake_client.messages.last_call_kwargs["messages"][0]["content"]
    assert "scan.pdf" in sent_user
    assert "לא נמצא טקסט" in sent_user
