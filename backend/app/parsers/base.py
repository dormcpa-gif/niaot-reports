"""Parser contract that every broker/document parser must implement.

Adding a new source (Schwab, eToro, TradeStation, IBKR UK, K-1, 1040, ...)
later means writing one class here that returns the same
`NormalizedStatement` shape — nothing in mapping/ or services/ changes.
"""

from __future__ import annotations

from typing import Protocol

from app.models.transactions import NormalizedStatement


class StatementParser(Protocol):
    broker_name: str

    def parse(self, file_bytes: bytes, statement_id: str) -> NormalizedStatement:
        """Parse raw PDF bytes into a NormalizedStatement."""
        ...
