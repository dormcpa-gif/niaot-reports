"""Normalized transaction models. Every parser (IBKR today, others later)
must produce these regardless of the source broker's own format."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Currency(str, Enum):
    USD = "USD"
    ILS = "ILS"
    EUR = "EUR"
    GBP = "GBP"


class TransactionKind(str, Enum):
    DIVIDEND = "dividend"
    INTEREST = "interest"
    TRADE = "trade"
    FEE = "fee"


class HoldingTerm(str, Enum):
    SHORT = "short"  # מדרגת רווח הון קצר טווח
    LONG = "long"  # מדרגת רווח הון ארוך טווח


class SourceRef(BaseModel):
    """Points back at the exact row in the source PDF this figure came from,
    so the explanation report can cite it."""

    statement_id: str
    page: int
    table_name: str
    row_text: str


class Dividend(BaseModel):
    kind: TransactionKind = TransactionKind.DIVIDEND
    pay_date: date
    symbol: str
    isin: str | None = None
    description: str | None = None
    gross_amount: float
    currency: Currency = Currency.USD
    withholding_tax: float = 0.0
    source: SourceRef


class InterestItem(BaseModel):
    kind: TransactionKind = TransactionKind.INTEREST
    value_date: date
    description: str
    amount: float
    currency: Currency = Currency.USD
    source: SourceRef


class Trade(BaseModel):
    """One realized-gain trade line, taken from IBKR's Trades table
    (already netted to a single realized P/L per closing lot)."""

    kind: TransactionKind = TransactionKind.TRADE
    symbol: str
    isin: str | None = None
    close_date: date
    proceeds: float
    cost_basis: float
    realized_pnl: float
    holding_term: HoldingTerm
    currency: Currency = Currency.USD
    source: SourceRef


class FeeItem(BaseModel):
    kind: TransactionKind = TransactionKind.FEE
    description: str
    value_date: date
    amount: float
    currency: Currency = Currency.USD
    source: SourceRef


class NormalizedStatement(BaseModel):
    statement_id: str
    broker: str = "IBKR"
    period_start: date
    period_end: date
    base_currency: Currency = Currency.USD
    dividends: list[Dividend] = Field(default_factory=list)
    interest: list[InterestItem] = Field(default_factory=list)
    trades: list[Trade] = Field(default_factory=list)
    fees: list[FeeItem] = Field(default_factory=list)
    # Best-effort per-symbol net sale proceeds for the "סכום המכירות" total
    # in Nispach C, taken from the Trades section's "Total <Symbol>" lines.
    # It's a NET figure (buys and sells for the symbol netted together),
    # so it undercounts true gross sale proceeds for a symbol that was
    # both bought and sold in the same year -- flagged as an
    # approximation the accountant should verify, not a precise total.
    sale_proceeds_by_symbol: dict[str, float] = Field(default_factory=dict)
