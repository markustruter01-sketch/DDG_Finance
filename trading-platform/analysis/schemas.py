"""
Pydantic Schemas — Structured LLM Output
------------------------------------------
Forces the LLM to produce strictly-typed JSON. If the model output cannot be
parsed into these models, the analysis cycle raises an error rather than
proceeding with malformed data.

AllocationSlot  — one of the 10 capital allocation positions
AnalysisOutput  — the full response: market regime summary + 10 slots

Crypto-only mode (off-hours):
CryptoAllocationSlot — one of 6 crypto capital allocation positions
CryptoAnalysisOutput — crypto-only response: 6 slots across raw crypto pairs
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AssetClass = Literal["crypto", "commodity", "currency", "wildcard", "cash", "crypto_spot"]

VALID_TICKERS: dict[str, list[str]] = {
    "crypto":      ["BITO", "IBIT", "GBTC", "ETHA"],
    "commodity":   ["GLD", "SLV", "USO", "DBA", "PDBC", "CPER"],
    "currency":    ["UUP", "FXE", "FXY", "FXB", "EUO", "YCS"],
    "wildcard":    ["QQQ", "SPY", "TLT", "HYG", "EEM"],
    "cash":        ["SGOV"],
    "crypto_spot": ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"],
}

ALL_VALID_TICKERS: set[str] = {t for tickers in VALID_TICKERS.values() for t in tickers}

CRYPTO_SPOT_TICKERS: set[str] = set(VALID_TICKERS["crypto_spot"])

SLOT_LIMITS: dict[str, tuple[int, int]] = {
    "crypto":      (2, 4),
    "commodity":   (3, 6),
    "currency":    (1, 6),
    "wildcard":    (1, 6),
    "cash":        (0, 5),
    "crypto_spot": (0, 6),
}

CRYPTO_ONLY_SLOT_LIMITS: dict[str, tuple[int, int]] = {
    "crypto_spot": (4, 6),
    "cash":        (0, 2),
}


def is_crypto_pair(ticker: str) -> bool:
    return "/" in ticker


class AllocationSlot(BaseModel):
    slot: int = Field(..., ge=1, le=10)
    ticker: str
    asset_class: AssetClass
    conviction_score: float = Field(..., ge=0.0, le=1.0)
    kelly_fraction: float = Field(..., ge=0.0, le=0.25)
    thesis: str = Field(..., min_length=10)
    stop_loss_pct: float = Field(..., lt=0.0)
    take_profit_pct: float = Field(..., gt=0.0)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if v not in ALL_VALID_TICKERS:
            raise ValueError(
                f"Ticker '{v}' is not in the approved universe. "
                f"Valid: {sorted(ALL_VALID_TICKERS)}"
            )
        return v

    @field_validator("stop_loss_pct")
    @classmethod
    def validate_stop_loss(cls, v: float) -> float:
        if v < -0.30:
            raise ValueError("stop_loss_pct cannot exceed -30% — too risky")
        return round(v, 4)

    @field_validator("take_profit_pct")
    @classmethod
    def validate_take_profit(cls, v: float) -> float:
        if v > 0.50:
            raise ValueError("take_profit_pct cannot exceed +50% — unrealistic")
        return round(v, 4)

    @model_validator(mode="after")
    def validate_ticker_asset_class_match(self) -> "AllocationSlot":
        expected = VALID_TICKERS.get(self.asset_class, [])
        if self.ticker not in expected:
            raise ValueError(
                f"Ticker '{self.ticker}' does not belong to asset_class "
                f"'{self.asset_class}'. Expected one of: {expected}"
            )
        return self


class AnalysisOutput(BaseModel):
    market_regime: str = Field(..., min_length=10)
    allocations: list[AllocationSlot] = Field(..., min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_slot_numbers(self) -> "AnalysisOutput":
        slots = sorted(a.slot for a in self.allocations)
        if slots != list(range(1, 11)):
            raise ValueError(f"Slots must be numbered 1–10, got: {slots}")
        return self

    @model_validator(mode="after")
    def validate_category_counts(self) -> "AnalysisOutput":
        counts: dict[str, int] = {}
        for slot in self.allocations:
            counts[slot.asset_class] = counts.get(slot.asset_class, 0) + 1

        for cat, (min_c, max_c) in SLOT_LIMITS.items():
            actual = counts.get(cat, 0)
            if actual < min_c:
                raise ValueError(
                    f"Asset class '{cat}' requires at least {min_c} slots, got {actual}"
                )
            if actual > max_c:
                raise ValueError(
                    f"Asset class '{cat}' allows at most {max_c} slots, got {actual}"
                )
        return self

    def low_conviction_slots(self) -> list[AllocationSlot]:
        from config.settings import settings
        return [a for a in self.allocations if a.conviction_score < settings.conviction_threshold]

    def summary(self) -> str:
        lines = [f"Market Regime: {self.market_regime}", ""]
        for a in sorted(self.allocations, key=lambda x: x.slot):
            flag = " [CASH]" if a.ticker == "SGOV" else ""
            lines.append(
                f"  Slot {a.slot:2d}: {a.ticker:6s} | {a.asset_class:10s} | "
                f"conv={a.conviction_score:.0%} | kelly={a.kelly_fraction:.1%} | "
                f"SL={a.stop_loss_pct:.1%} TP={a.take_profit_pct:.1%}{flag}"
            )
        return "\n".join(lines)


class CryptoAllocationSlot(BaseModel):
    slot: int = Field(..., ge=1, le=6)
    ticker: str
    asset_class: Literal["crypto_spot", "cash"]
    conviction_score: float = Field(..., ge=0.0, le=1.0)
    kelly_fraction: float = Field(..., ge=0.0, le=0.25)
    thesis: str = Field(..., min_length=10)
    stop_loss_pct: float = Field(..., lt=0.0)
    take_profit_pct: float = Field(..., gt=0.0)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        allowed = VALID_TICKERS["crypto_spot"] + VALID_TICKERS["cash"]
        if v not in allowed:
            raise ValueError(
                f"Ticker '{v}' is not in the crypto-only universe. "
                f"Valid: {sorted(allowed)}"
            )
        return v

    @field_validator("stop_loss_pct")
    @classmethod
    def validate_stop_loss(cls, v: float) -> float:
        if v < -0.30:
            raise ValueError("stop_loss_pct cannot exceed -30% — too risky")
        return round(v, 4)

    @field_validator("take_profit_pct")
    @classmethod
    def validate_take_profit(cls, v: float) -> float:
        if v > 0.50:
            raise ValueError("take_profit_pct cannot exceed +50% — unrealistic")
        return round(v, 4)

    @model_validator(mode="after")
    def validate_ticker_asset_class_match(self) -> "CryptoAllocationSlot":
        expected = VALID_TICKERS.get(self.asset_class, [])
        if self.ticker not in expected:
            raise ValueError(
                f"Ticker '{self.ticker}' does not belong to asset_class "
                f"'{self.asset_class}'. Expected one of: {expected}"
            )
        return self


class CryptoAnalysisOutput(BaseModel):
    market_regime: str = Field(..., min_length=10)
    allocations: list[CryptoAllocationSlot] = Field(..., min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_slot_numbers(self) -> "CryptoAnalysisOutput":
        slots = sorted(a.slot for a in self.allocations)
        if slots != list(range(1, 7)):
            raise ValueError(f"Slots must be numbered 1–6, got: {slots}")
        return self

    @model_validator(mode="after")
    def validate_category_counts(self) -> "CryptoAnalysisOutput":
        counts: dict[str, int] = {}
        for slot in self.allocations:
            counts[slot.asset_class] = counts.get(slot.asset_class, 0) + 1

        for cat, (min_c, max_c) in CRYPTO_ONLY_SLOT_LIMITS.items():
            actual = counts.get(cat, 0)
            if actual < min_c:
                raise ValueError(
                    f"Asset class '{cat}' requires at least {min_c} slots, got {actual}"
                )
            if actual > max_c:
                raise ValueError(
                    f"Asset class '{cat}' allows at most {max_c} slots, got {actual}"
                )
        return self

    def low_conviction_slots(self) -> list[CryptoAllocationSlot]:
        from config.settings import settings
        return [a for a in self.allocations if a.conviction_score < settings.conviction_threshold]

    def summary(self) -> str:
        lines = [f"Market Regime (Crypto): {self.market_regime}", ""]
        for a in sorted(self.allocations, key=lambda x: x.slot):
            flag = " [CASH]" if a.ticker == "SGOV" else ""
            lines.append(
                f"  Slot {a.slot}: {a.ticker:8s} | {a.asset_class:12s} | "
                f"conv={a.conviction_score:.0%} | kelly={a.kelly_fraction:.1%} | "
                f"SL={a.stop_loss_pct:.1%} TP={a.take_profit_pct:.1%}{flag}"
            )
        return "\n".join(lines)
