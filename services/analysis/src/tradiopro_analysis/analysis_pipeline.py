"""In-process orchestration of market, liquidity, and trade validation."""

from dataclasses import dataclass
from typing import Sequence

from .liquidity_sweeps import LiquiditySweepEvent, detect_liquidity_sweeps
from .market_structure import (
    AnalysisResult,
    Candle,
    analyze_market_structure,
)
from .risk_validation import (
    ProposedTrade,
    TradeValidationResult,
    validate_trade_geometry,
)


@dataclass(frozen=True, slots=True)
class AnalysisPipelineResult:
    market_structure: AnalysisResult
    liquidity_sweeps: tuple[LiquiditySweepEvent, ...]
    trade_validation: TradeValidationResult


def analyze_market_and_trade(
    candles: Sequence[Candle],
    trade: ProposedTrade,
) -> AnalysisPipelineResult:
    """Analyze candles and validate the separately supplied trade plan."""
    market_structure = analyze_market_structure(candles)
    liquidity_sweeps = detect_liquidity_sweeps(candles, market_structure)
    trade_validation = validate_trade_geometry(trade)
    return AnalysisPipelineResult(
        market_structure=market_structure,
        liquidity_sweeps=liquidity_sweeps,
        trade_validation=trade_validation,
    )
