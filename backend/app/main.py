from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_clients import router as clients_router
from app.api.routes_reports import router as reports_router
from app.api.routes_statements import router as statements_router
from app.db.session import init_db

app = FastAPI(title="מערכת דוחות ני\"ע - IBKR to Nispach C/D")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(clients_router)
app.include_router(statements_router)
app.include_router(reports_router)
