"""Calls Claude (Anthropic API) with the tax-analysis system prompt in
app/resources/tax_analysis_system_prompt.md against a set of uploaded US
tax documents (1040 + schedules + K-1 + state returns + broker 1099s),
and returns the narrative + structured JSON working paper described in
that prompt's section 8.

This is a fundamentally different kind of "parser" from the
IBKR/eToro/Schwab/... modules in app/parsers/: those extract numbers
deterministically via regex/table structure. Residency, foreign-tax-
credit direction, basket allocation etc. require actual judgment, which
is exactly what the system prompt asks the model to reason through --
while still never emitting a final position (see the prompt's own
"role" and "reliability rules" sections). Output is always a draft for
the accountant to review, the same needs_review philosophy as every
other module in this codebase, just carried by prose/JSON instead of a
`needs_review` boolean.
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber
from anthropic import Anthropic

from app.models.analysis import DeepAnalysisResult, InputDocumentInfo

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "resources" / "tax_analysis_system_prompt.md"
_DEFAULT_MODEL = "claude-sonnet-5"
_MAX_OUTPUT_TOKENS = 8000

_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "לא הוגדר מפתח API של Anthropic (ANTHROPIC_API_KEY). "
            "יש להגדיר משתנה סביבה זה (מקומית או ב-Render) לפני שימוש בניתוח המעמיק מבוסס-הבינה המלאכותית."
        )
    return Anthropic(api_key=api_key)


def extract_text_from_upload(filename: str, content: bytes) -> tuple[str, str | None]:
    """Best-effort text extraction for one uploaded document.
    Returns (text, note) -- note is set when extraction likely failed
    (e.g. a scanned PDF with no text layer), so the caller can flag it
    as a missing/unreadable document rather than silently sending an
    empty document to the model."""
    if content[:5] == b"%PDF-":
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception as e:
            return "", f"שגיאה בפתיחת ה-PDF: {e}"
        if len(text.strip()) < 20:
            return text, "לא נמצא טקסט הניתן לחילוץ (ייתכן שזהו מסמך סרוק/תמונה ללא שכבת טקסט)."
        return text, None

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "", "לא ניתן היה לפענח את הקובץ כ-PDF או כטקסט/CSV תקין."
    if not text.strip():
        return text, "הקובץ ריק."
    return text, None


def _build_user_message(documents: list[tuple[InputDocumentInfo, str]], client_context: str) -> str:
    parts = [
        "להלן קבצי המקור שהועלו לניתוח. כל קובץ מופרד בכותרת עם שם הקובץ. "
        "מסמכים עם הערת 'לא נמצא טקסט' יש להתייחס אליהם כמסמך חסר/לא קריא, לא לנחש את תוכנם.",
    ]
    if client_context:
        parts.append(f"\nהקשר נוסף שסופק על ידי המשתמש:\n{client_context}\n")
    for info, text in documents:
        parts.append(f"\n===== מסמך: {info.filename} =====")
        if info.extraction_note:
            parts.append(f"[הערה: {info.extraction_note}]")
        parts.append(text)
    return "\n".join(parts)


def _parse_structured_json(response_text: str) -> tuple[dict[str, Any] | None, str | None]:
    m = _JSON_BLOCK_RE.search(response_text)
    if not m:
        return None, "לא נמצא בלוק ```json בתשובת המודל -- מוצג הסיכום המילולי בלבד."
    try:
        return json.loads(m.group(1)), None
    except json.JSONDecodeError as e:
        return None, f"בלוק ה-JSON שהוחזר אינו תקין ({e}) -- מוצג הסיכום המילולי בלבד."


def run_deep_analysis(
    client_id: str,
    tax_year: int,
    uploaded_files: list[tuple[str, bytes]],
    client_context: str = "",
    model: str | None = None,
) -> DeepAnalysisResult:
    """uploaded_files: [(filename, raw_bytes), ...] for the 1040/schedules/
    K-1/state returns/broker statements the accountant wants analyzed
    together for one client/tax year."""
    if not uploaded_files:
        raise ValueError("יש להעלות לפחות מסמך אחד לניתוח.")

    input_docs: list[InputDocumentInfo] = []
    extracted: list[tuple[InputDocumentInfo, str]] = []
    for filename, content in uploaded_files:
        text, note = extract_text_from_upload(filename, content)
        info = InputDocumentInfo(filename=filename, extracted_chars=len(text), extraction_note=note)
        input_docs.append(info)
        extracted.append((info, text))

    if all(d.extraction_note is not None for d in input_docs):
        raise ValueError(
            "לא ניתן היה לחלץ טקסט קריא מאף אחד מהקבצים שהועלו (ראו הערות לכל קובץ). "
            "ודאו שמדובר בקובצי PDF עם שכבת טקסט (לא סרוקים) או בקבצי טקסט/CSV תקינים."
        )

    client = _get_client()
    resolved_model = model or os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(extracted, client_context)

    response = client.messages.create(
        model=resolved_model,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    response_text = "".join(block.text for block in response.content if block.type == "text")

    structured, parse_error = _parse_structured_json(response_text)
    narrative = _JSON_BLOCK_RE.sub("", response_text).strip()

    return DeepAnalysisResult(
        id=str(uuid.uuid4()),
        client_id=client_id,
        tax_year=tax_year,
        created_at=datetime.utcnow(),
        model=resolved_model,
        input_documents=input_docs,
        narrative=narrative,
        structured=structured,
        structured_parse_error=parse_error,
    )
