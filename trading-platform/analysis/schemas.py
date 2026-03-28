"""
Pydantic Schemas — Structured LLM Output
------------------------------------------
v4.3 — Leveraged Risk Satellite Bucket + SPY EMA Anchor

RegimeAnalysisOutput  — variable-slot allocation driven by Bull/Bear/Sideways regime
CryptoAnalysisOutput  — off-hours crypto-only allocation (BTC/USD, ETH/USD)

Asset universe (19 instruments + SGOV):
  Equities (Sectors)  : SPY, QQQ, XLK, XLF, XLV, XLE, IWM
  Safe Havens/Bonds   : TLT, IEF, GLD, SLV
  Commodities         : USO, PDBC
  Crypto Spot         : BTC/USD, ETH/USD
  Leveraged Risk      : TQQQ, SOXL, UPRO  ← NEW (Bull-only, 20% total cap)
  Cash                : SGOV

Position sizing rules (enforced in executor, not here):
  - Max single position: 10% of equity (hard cap)
  - Leveraged Risk group: max 20% combined (enforced in allocator)
  - Leveraged Risk allowed ONLY in confirmed Bull regime (vetted by SPY EMA anchor)
  - No margin: trades blocked when available cash ≤ 0
  - LLM kelly_fractions sum ≤ 1.0 as always

Slot limits: 10 active slots maximum.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


REGIME_UNIVERSE: dict[str, list[str]] = {
    "equity":          ["SPY", "QQQ", "XLK", "XLF", "XLV", "XLE", "IWM"],
    "safe_haven":      ["TLT", "IEF", "GLD", "SLV"],
    "commodity":       ["USO", "PDBC"],
    "crypto_spot":     ["BTC/USD", "ETH/USD"],
    "leveraged_risk":  ["TQQQ", "SOXL", "UPRO"],
    "cash":            ["SGOV"],
}

ALL_REGIME_TICKERS: set[str] = {t for tickers in REGIME_UNIVERSE.values() for t in tickers}

CRYPTO_SPOT_TICKERS: set[str] = set(REGIME_UNIVERSE["crypto_spot"])
LEVERAGED_RISK_TICKERS: set[str] = set(REGIME_UNIVERSE["leveraged_risk"])

RegimeLabel = Literal["Bull", "Bear", "Sideways"]
AssetClass = Literal["equity", "safe_haven", "commodity", "crypto_spot", "leveraged_risk", "cash"]
CryptoAssetClass = Literal["crypto_spot", "cash"]


def is_crypto_pair(ticker: str) -> bool:
    return "/" in ticker


def is_leveraged_risk(ticker: str) -> bool:
    return ticker in LEVERAGED_RISK_TICKERS


class RegimeAllocationSlot(BaseModel):
    slot: int = Field(..., ge=1, le=10)
    ticker: str
    asset_class: AssetClass
    conviction_score: float = Field(..., ge=0.0, le=1.0)
    kelly_fraction: float = Field(..., ge=0.0, le=1.0)
    thesis: str = Field(..., min_length=10)
    stop_loss_pct: float = Field(..., lt=0.0)
    take_profit_pct: float = Field(..., gt=0.0)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if v not in ALL_REGIME_TICKERS:
            raise ValueError(
                f"Ticker '{v}' is not in the approved universe. "
                f"Valid: {sorted(ALL_REGIME_TICKERS)}"
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
        if v > 0.60:
            raise ValueError("take_profit_pct cannot exceed +60% — unrealistic")
        return round(v, 4)

    @model_validator(mode="after")
    def validate_ticker_asset_class_match(self) -> "RegimeAllocationSlot":
        expected = REGIME_UNIVERSE.get(self.asset_class, [])
        if self.ticker not in expected:
            raise ValueError(
                f"Ticker '{self.ticker}' does not belong to asset_class "
                f"'{self.asset_class}'. Expected one of: {expected}"
            )
        return self


class RegimeAnalysisOutput(BaseModel):
    regime: RegimeLabel
    regime_rationale: str = Field(..., min_length=20)
    allocations: list[RegimeAllocationSlot] = Field(..., min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_slot_numbers(self) -> "RegimeAnalysisOutput":
        n = len(self.allocations)
        expected = list(range(1, n + 1))
        actual = sorted(a.slot for a in self.allocations)
        if actual != expected:
            raise ValueError(
                f"Slots must be numbered 1–{n} sequentially, got: {actual}"
            )
        return self

    @model_validator(mode="after")
    def validate_regime_rules(self) -> "RegimeAnalysisOutput":
        non_cash = [a for a in self.allocations if a.ticker != "SGOV"]
        tickers = [a.ticker for a in non_cash]

        if self.regime == "Bull":
            risk_assets = set(
                REGIME_UNIVERSE["equity"]
                + REGIME_UNIVERSE["crypto_spot"]
                + REGIME_UNIVERSE["commodity"]
                + REGIME_UNIVERSE["leveraged_risk"]
            )
            bad = [t for t in tickers if t not in risk_assets]
            if bad:
                raise ValueError(
                    f"Bull regime: only equity/crypto_spot/commodity/leveraged_risk allowed, got: {bad}. "
                    f"Approved: {sorted(risk_assets)}"
                )
            if len(non_cash) < 1 or len(non_cash) > 7:
                raise ValueError(
                    f"Bull regime requires 1–7 risk asset slots, got {len(non_cash)}."
                )

        elif self.regime == "Bear":
            safe_assets = set(REGIME_UNIVERSE["safe_haven"] + ["SGOV"])
            bad = [t for t in tickers if t not in safe_assets]
            if bad:
                raise ValueError(
                    f"Bear regime: only safe_haven/cash allowed, got: {bad}. "
                    f"Use TLT, IEF, GLD, SLV, or SGOV if safe havens have negative momentum. "
                    f"Leveraged ETFs (TQQQ/SOXL/UPRO) are strictly forbidden in Bear regime."
                )

        elif self.regime == "Sideways":
            if any(t in LEVERAGED_RISK_TICKERS for t in tickers):
                bad_letf = [t for t in tickers if t in LEVERAGED_RISK_TICKERS]
                raise ValueError(
                    f"Sideways regime: leveraged ETFs {bad_letf} are forbidden. "
                    f"Leveraged risk positions are only permitted in confirmed Bull regime."
                )

        return self

    @model_validator(mode="after")
    def validate_kelly_sum(self) -> "RegimeAnalysisOutput":
        total = sum(a.kelly_fraction for a in self.allocations if a.ticker != "SGOV")
        if total > 1.01:
            raise ValueError(
                f"Total kelly_fraction sum {total:.3f} exceeds 1.0 — "
                f"allocations cannot exceed 100% of equity."
            )
        return self

    def low_conviction_slots(self) -> list[RegimeAllocationSlot]:
        from config.settings import settings
        return [a for a in self.allocations if a.conviction_score < settings.conviction_threshold]

    def summary(self) -> str:
        lines = [
            f"Regime: {self.regime}",
            f"Rationale: {self.regime_rationale}",
            "",
        ]
        for a in sorted(self.allocations, key=lambda x: x.slot):
            flag = " [CASH]" if a.ticker == "SGOV" else ""
            letf = " [LETF]" if a.ticker in LEVERAGED_RISK_TICKERS else ""
            lines.append(
                f"  Slot {a.slot}: {a.ticker:10s} | {a.asset_class:15s} | "
                f"conv={a.conviction_score:.0%} | kelly={a.kelly_fraction:.1%} | "
                f"SL={a.stop_loss_pct:.1%} TP={a.take_profit_pct:.1%}{flag}{letf}"
            )
        return "\n".join(lines)


class CryptoAllocationSlot(BaseModel):
    slot: int = Field(..., ge=1, le=3)
    ticker: str
    asset_class: CryptoAssetClass
    conviction_score: float = Field(..., ge=0.0, le=1.0)
    kelly_fraction: float = Field(..., ge=0.0, le=1.0)
    thesis: str = Field(..., min_length=10)
    stop_loss_pct: float = Field(..., lt=0.0)
    take_profit_pct: float = Field(..., gt=0.0)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        allowed = REGIME_UNIVERSE["crypto_spot"] + REGIME_UNIVERSE["cash"]
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
            raise ValueError("stop_loss_pct cannot exceed -30%")
        return round(v, 4)

    @field_validator("take_profit_pct")
    @classmethod
    def validate_take_profit(cls, v: float) -> float:
        if v > 0.60:
            raise ValueError("take_profit_pct cannot exceed +60%")
        return round(v, 4)

    @model_validator(mode="after")
    def validate_ticker_asset_class_match(self) -> "CryptoAllocationSlot":
        expected = REGIME_UNIVERSE.get(self.asset_class, [])
        if self.ticker not in expected:
            raise ValueError(
                f"Ticker '{self.ticker}' does not belong to asset_class "
                f"'{self.asset_class}'. Expected one of: {expected}"
            )
        return self


class CryptoAnalysisOutput(BaseModel):
    market_regime: str = Field(..., min_length=10)
    allocations: list[CryptoAllocationSlot] = Field(..., min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_slot_numbers(self) -> "CryptoAnalysisOutput":
        n = len(self.allocations)
        actual = sorted(a.slot for a in self.allocations)
        if actual != list(range(1, n + 1)):
            raise ValueError(f"Slots must be numbered 1–{n} sequentially, got: {actual}")
        return self

    @model_validator(mode="after")
    def validate_kelly_sum(self) -> "CryptoAnalysisOutput":
        total = sum(a.kelly_fraction for a in self.allocations if a.ticker != "SGOV")
        if total > 1.01:
            raise ValueError(f"Total kelly_fraction {total:.3f} exceeds 1.0")
        return self

    def low_conviction_slots(self) -> list[CryptoAllocationSlot]:
        from config.settings import settings
        return [a for a in self.allocations if a.conviction_score < settings.conviction_threshold]

    def summary(self) -> str:
        lines = [f"Market Regime (Crypto): {self.market_regime}", ""]
        for a in sorted(self.allocations, key=lambda x: x.slot):
            flag = " [CASH]" if a.ticker == "SGOV" else ""
            lines.append(
                f"  Slot {a.slot}: {a.ticker:10s} | {a.asset_class:12s} | "
                f"conv={a.conviction_score:.0%} | kelly={a.kelly_fraction:.1%} | "
                f"SL={a.stop_loss_pct:.1%} TP={a.take_profit_pct:.1%}{flag}"
            )
        return "\n".join(lines)
