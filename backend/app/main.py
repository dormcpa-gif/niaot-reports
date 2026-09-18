from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import bootstrap_admin_if_needed, get_current_user
from app.api.routes_admin import router as admin_router
from app.api.routes_analysis import router as analysis_router
from app.api.routes_auth import router as auth_router
from app.api.routes_clients import router as clients_router
from app.api.routes_reports import router as reports_router
from app.api.routes_statements import router as statements_router
from app.db.session import SessionLocal, init_db

app = FastAPI(title="מערכת דוחות ני\"ע - IBKR to Nispach C/D")

_extra_origins = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://niaot-reports.netlify.app",
        *_extra_origins,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        bootstrap_admin_if_needed(db)
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(clients_router, dependencies=[Depends(get_current_user)])
app.include_router(statements_router, dependencies=[Depends(get_current_user)])
app.include_router(reports_router, dependencies=[Depends(get_current_user)])
app.include_router(analysis_router, dependencies=[Depends(get_current_user)])
