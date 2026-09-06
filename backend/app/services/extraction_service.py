"""Orchestrates: PDF bytes -> parser -> NormalizedStatement -> classified
line items ready for the review screen / report builders."""

from __future__ import annotations

from pydantic import BaseModel

from app.mapping.classification import (
    ClassifiedItem,
    classify_dividend,
    classify_fee,
    classify_interest,
    classify_trade,
)
from app.models.transactions import Dividend, NormalizedStatement
from app.parsers.base import StatementParser
from app.parsers.etoro_statement import EToroStatementParser
from app.parsers.form_1040 import Form1040Parser
from app.parsers.ibkr_activity import IBKRActivityParser
from app.parsers.k1_schedule import K1ScheduleParser
from app.parsers.schwab_statement import SchwabStatementParser
from app.parsers.tradestation_export import TradeStationExportParser

# IBKR also covers IBKR (U.K.) Limited / Central Europe accounts (same
# statement layout, GBP/EUR base currency) -- see ibkr_activity.py.
# Every entry below except IBKR itself is unverified against a real
# statement -- see each parser module's docstring before trusting its
# output the way the IBKR one has been validated.
_PARSERS: dict[str, StatementParser] = {
    "IBKR": IBKRActivityParser(),
    "ETORO": EToroStatementParser(),
    "SCHWAB": SchwabStatementParser(),
    "TD_AMERITRADE": SchwabStatementParser(),  # TD Ameritrade migrated onto Schwab's platform/statement format
    "TRADESTATION": TradeStationExportParser(),
    "K1": K1ScheduleParser(),
    "FORM_1040": Form1040Parser(),
}


def get_parser(broker: str) -> StatementParser:
    try:
        return _PARSERS[broker]
    except KeyError as e:
        raise ValueError(f"No parser registered for broker '{broker}'. Available: {list(_PARSERS)}") from e


class ExtractionResult(BaseModel):
    statement: NormalizedStatement
    classified: list[ClassifiedItem]
    dividends_by_id: dict[str, Dividend]


def extract_and_classify(file_bytes: bytes, statement_id: str, broker: str = "IBKR") -> ExtractionResult:
    parser = get_parser(broker)
    statement = parser.parse(file_bytes, statement_id)

    classified: list[ClassifiedItem] = []
    dividends_by_id: dict[str, Dividend] = {}

    for d in statement.dividends:
        item = classify_dividend(d)
        dividends_by_id[item.source_id] = d
        classified.append(item)

    for i in statement.interest:
        classified.append(classify_interest(i))

    for t in statement.trades:
        classified.append(classify_trade(t))

    for f in statement.fees:
        classified.append(classify_fee(f))

    return ExtractionResult(statement=statement, classified=classified, dividends_by_id=dividends_by_id)
