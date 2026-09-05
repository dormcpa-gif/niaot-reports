"""Minimal persistence layer.

We don't model every transaction field relationally -- the normalized
statement and its classification are stored as JSON blobs keyed by
statement id, with a separate `overrides` JSON blob for whatever the
accountant edits on the review screen (per-item Nispach D field / Nispach
C bracket changes). That's enough for the MVP: it lets the review screen
persist edits across requests without inventing a full transaction
schema that would just have to change shape the moment a second broker
parser is added.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class ClientORM(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    full_name: Mapped[str] = mapped_column(String)
    tax_file_number: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    statements: Mapped[list["StatementORM"]] = relationship(back_populates="client")


class StatementORM(Base):
    __tablename__ = "statements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"))
    tax_year: Mapped[int] = mapped_column()
    broker: Mapped[str] = mapped_column(String)
    original_filename: Mapped[str] = mapped_column(String)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # NormalizedStatement.model_dump(mode="json")
    normalized_statement_json: Mapped[dict] = mapped_column(JSON)
    # list[ClassifiedItem] as produced at parse time (dump mode="json")
    classified_items_json: Mapped[dict] = mapped_column(JSON)
    # accountant edits: {"field_overrides": {source_id: nispach_d_field|None},
    #                    "bracket_overrides": {source_id: "30"}}
    overrides_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # [{"currency": "USD", "date": "2025-01-03", "rate": 3.62}, ...]
    fx_rates_json: Mapped[dict] = mapped_column(JSON, default=dict)

    client: Mapped[ClientORM] = relationship(back_populates="statements")
