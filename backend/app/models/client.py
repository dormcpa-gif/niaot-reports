from __future__ import annotations

from pydantic import BaseModel


class Client(BaseModel):
    id: str
    full_name: str
    tax_file_number: str | None = None  # מספר תיק ברשות המסים


class TaxYear(BaseModel):
    client_id: str
    year: int
