from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.models import DeepAnalysisORM
from app.db.session import get_session
from app.models.analysis import DeepAnalysisResult, DeepAnalysisSummary, InputDocumentInfo
from app.services.llm_analysis_service import run_deep_analysis

router = APIRouter(prefix="/analysis", tags=["analysis"])

_EXCERPT_LEN = 240


def _summary_from_orm(orm: DeepAnalysisORM) -> DeepAnalysisSummary:
    filenames = [d.get("filename", "") for d in orm.input_documents_json]
    excerpt = orm.narrative[:_EXCERPT_LEN] + ("…" if len(orm.narrative) > _EXCERPT_LEN else "")
    return DeepAnalysisSummary(
        id=orm.id,
        client_id=orm.client_id,
        tax_year=orm.tax_year,
        created_at=orm.created_at,
        input_filenames=filenames,
        narrative_excerpt=excerpt,
    )


def _result_from_orm(orm: DeepAnalysisORM) -> DeepAnalysisResult:
    return DeepAnalysisResult(
        id=orm.id,
        client_id=orm.client_id,
        tax_year=orm.tax_year,
        created_at=orm.created_at,
        model=orm.model,
        input_documents=[InputDocumentInfo.model_validate(d) for d in orm.input_documents_json],
        narrative=orm.narrative,
        structured=orm.structured_json,
        structured_parse_error=orm.structured_parse_error,
    )


@router.get("/by-client/{client_id}", response_model=list[DeepAnalysisSummary])
def list_analyses_for_client(client_id: str, session: Session = Depends(get_session)) -> list[DeepAnalysisSummary]:
    rows = (
        session.query(DeepAnalysisORM)
        .filter(DeepAnalysisORM.client_id == client_id)
        .order_by(DeepAnalysisORM.created_at.desc())
        .all()
    )
    return [_summary_from_orm(r) for r in rows]


@router.get("/{analysis_id}", response_model=DeepAnalysisResult)
def get_analysis(analysis_id: str, session: Session = Depends(get_session)) -> DeepAnalysisResult:
    orm = session.get(DeepAnalysisORM, analysis_id)
    if orm is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _result_from_orm(orm)


@router.post("/deep", response_model=DeepAnalysisResult)
async def create_deep_analysis(
    client_id: str = Form(...),
    tax_year: int = Form(...),
    client_context: str = Form(""),
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> DeepAnalysisResult:
    uploaded: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        if content:
            uploaded.append((f.filename or "document", content))

    try:
        result = run_deep_analysis(client_id, tax_year, uploaded, client_context)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # Anthropic SDK errors (auth, rate limit, network, ...)
        raise HTTPException(status_code=502, detail=f"שגיאה בקריאה למודל השפה: {e}") from e

    orm = DeepAnalysisORM(
        id=result.id,
        client_id=result.client_id,
        tax_year=result.tax_year,
        created_at=result.created_at,
        model=result.model,
        input_documents_json=[d.model_dump(mode="json") for d in result.input_documents],
        narrative=result.narrative,
        structured_json=result.structured,
        structured_parse_error=result.structured_parse_error,
    )
    session.add(orm)
    session.commit()

    return result
