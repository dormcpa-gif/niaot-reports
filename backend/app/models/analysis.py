"""Models for the LLM-driven deep tax analysis feature (see
app/services/llm_analysis_service.py). Unlike the deterministic
IBKR/eToro/Schwab/... parsers, this reconciles a full set of US tax
documents (1040 + schedules + K-1 + state returns + broker 1099s) using
the judgment-heavy logic in
app/resources/tax_analysis_system_prompt.md -- residency, foreign tax
credit direction, basket allocation, etc. The model's output is a
*draft working paper*, never an auto-filed answer -- see that prompt's
own "role" section.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class InputDocumentInfo(BaseModel):
    filename: str
    extracted_chars: int
    extraction_note: str | None = None  # e.g. "no extractable text -- likely a scanned image"


class DeepAnalysisResult(BaseModel):
    id: str
    client_id: str
    tax_year: int
    created_at: datetime
    model: str
    input_documents: list[InputDocumentInfo]
    narrative: str
    # Best-effort parse of the ```json block the model returns per the
    # prompt's section 8.2. Left as a free-form dict (not a strict
    # Pydantic schema) because it's LLM-authored output we display for
    # human review, not something downstream code depends on structurally.
    structured: dict[str, Any] | None
    structured_parse_error: str | None


class DeepAnalysisSummary(BaseModel):
    id: str
    client_id: str
    tax_year: int
    created_at: datetime
    input_filenames: list[str]
    narrative_excerpt: str
