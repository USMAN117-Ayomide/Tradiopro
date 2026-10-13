from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from tradiopro_analysis import analysis_pipeline
from tradiopro_analysis.analysis_pipeline import (
    AnalysisPipelineResult,
    analyze_market_and_trade,
)
from tradiopro_analysis.liquidity_sweeps import (
    LiquiditySweepEvent,
    LiquiditySweepKind,
)
from tradiopro_analysis.market_structure import (
    AnalysisResult,
    Candle,
    Direction,
    TrendState,
)
from tradiopro_analysis.risk_validation import (
    ProposedTrade,
    TradeDirection,
    TradeValidationCode,
    TradeValidationError,
    TradeField,
    TradeValidationResult,
)


def candle(
    index: int,
    *,
    open_: float = 10,
    high: float = 12,
    low: float = 8,
    close: float = 10,
    volume: float = 100,
) -> Candle:
    return Candle(
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)
        + timedelta(minutes=index),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def candles_with_high_sweep() -> list[Candle]:
    bars = [candle(index) for index in range(9)]
    bars[2] = replace(bars[2], high=15)
    bars[5] = candle(5, open_=14, high=16, low=13, close=14)
    return bars


def valid_trade() -> ProposedTrade:
    return ProposedTrade(TradeDirection.LONG, 100, 95, 110)


def test_composes_real_components_and_detects_real_analyzer_sweep() -> None:
    bars = candles_with_high_sweep()
    trade = valid_trade()

    result = analyze_market_and_trade(bars, trade)

    assert isinstance(result, AnalysisPipelineResult)
    assert result.market_structure == analysis_pipeline.analyze_market_structure(bars)
    assert len(result.liquidity_sweeps) == 1
    sweep = result.liquidity_sweeps[0]
    assert isinstance(sweep, LiquiditySweepEvent)
    assert sweep.kind is LiquiditySweepKind.LIQUIDITY_SWEEP
    assert sweep.direction is Direction.BEARISH
    swing = next(
        swing
        for swing in result.market_structure.swings
        if swing.kind is sweep.swing_kind and swing.index == sweep.swing_index
    )
    assert sweep.swing_index == 2
    assert swing.index == 2
    assert swing.confirmed_at_index == 4
    assert sweep.index == 5
    assert sweep.index > swing.confirmed_at_index
    assert sweep.swing_price == 15
    assert result.trade_validation.is_valid
    assert result.trade_validation.risk_distance == 5
    assert result.trade_validation.reward_distance == 10
    assert result.trade_validation.reward_to_risk_ratio == 2


def test_calls_components_in_order_with_exact_input_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = [candle(index) for index in range(5)]
    trade = valid_trade()
    market_result = AnalysisResult((), (), TrendState.UNINITIALIZED)
    sweep_result = ()
    trade_result = TradeValidationResult(True, (), 5, 10, 2)
    calls: list[tuple[str, object, object | None]] = []

    def analyze(received_candles: object) -> AnalysisResult:
        calls.append(("market", received_candles, None))
        return market_result

    def detect(
        received_candles: object, received_analysis: object
    ) -> tuple[LiquiditySweepEvent, ...]:
        calls.append(("sweeps", received_candles, received_analysis))
        return sweep_result

    def validate(received_trade: object) -> TradeValidationResult:
        calls.append(("trade", received_trade, None))
        return trade_result

    monkeypatch.setattr(analysis_pipeline, "analyze_market_structure", analyze)
    monkeypatch.setattr(analysis_pipeline, "detect_liquidity_sweeps", detect)
    monkeypatch.setattr(analysis_pipeline, "validate_trade_geometry", validate)

    result = analyze_market_and_trade(bars, trade)

    assert [call[0] for call in calls] == ["market", "sweeps", "trade"]
    assert calls[0][1] is bars
    assert calls[1][1] is bars
    assert calls[1][2] is market_result
    assert calls[2][1] is trade
    assert result == AnalysisPipelineResult(market_result, sweep_result, trade_result)


def test_invalid_trade_preserves_successful_market_and_sweep_results() -> None:
    bars = candles_with_high_sweep()
    invalid_trade = ProposedTrade("LONG", 100, 95, 110)

    result = analyze_market_and_trade(bars, invalid_trade)

    assert len(result.market_structure.swings) > 0
    assert len(result.liquidity_sweeps) == 1
    assert result.trade_validation.is_valid is False
    assert TradeValidationError(
        field=TradeField.DIRECTION,
        code=TradeValidationCode.INVALID_DIRECTION,
    ) in result.trade_validation.errors
    assert result.trade_validation.risk_distance is None
    assert result.trade_validation.reward_distance is None
    assert result.trade_validation.reward_to_risk_ratio is None


def test_invalid_candles_propagate_analyzer_exception_without_later_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def unexpected_sweeps(
        candles: object, analysis: object
    ) -> tuple[LiquiditySweepEvent, ...]:
        calls.append("sweeps")
        raise AssertionError("sweep detection must not run after analyzer failure")

    def unexpected_validation(trade: object) -> TradeValidationResult:
        calls.append("trade")
        raise AssertionError("trade validation must not run after analyzer failure")

    monkeypatch.setattr(
        analysis_pipeline, "detect_liquidity_sweeps", unexpected_sweeps
    )
    monkeypatch.setattr(
        analysis_pipeline, "validate_trade_geometry", unexpected_validation
    )

    with pytest.raises(ValueError, match="at least five candles"):
        analyze_market_and_trade([], valid_trade())

    assert calls == []


def test_sweep_detection_failure_propagates_without_trade_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    expected_error = ValueError("invalid analysis result")

    def fail_sweep(
        candles: object, analysis: object
    ) -> tuple[LiquiditySweepEvent, ...]:
        calls.append("sweeps")
        raise expected_error

    def unexpected_validation(trade: object) -> TradeValidationResult:
        calls.append("trade")
        raise AssertionError("trade validation must not run after sweep failure")

    monkeypatch.setattr(analysis_pipeline, "detect_liquidity_sweeps", fail_sweep)
    monkeypatch.setattr(
        analysis_pipeline, "validate_trade_geometry", unexpected_validation
    )

    with pytest.raises(ValueError) as raised:
        analyze_market_and_trade([candle(index) for index in range(5)], valid_trade())

    assert raised.value is expected_error
    assert calls == ["sweeps"]


def test_non_proposed_trade_preserves_validator_type_error() -> None:
    with pytest.raises(TypeError, match="ProposedTrade"):
        analyze_market_and_trade([candle(index) for index in range(5)], object())  # type: ignore[arg-type]


def test_trade_is_supplied_unchanged_and_result_has_no_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = candles_with_high_sweep()
    trade = valid_trade()
    original_values = (
        trade.direction,
        trade.entry_price,
        trade.stop_loss_price,
        trade.take_profit_price,
    )
    seen_trades: list[object] = []
    validation = TradeValidationResult(True, (), 5, 10, 2)

    def validate(received_trade: object) -> TradeValidationResult:
        seen_trades.append(received_trade)
        return validation

    monkeypatch.setattr(analysis_pipeline, "validate_trade_geometry", validate)
    result = analyze_market_and_trade(bars, trade)

    assert seen_trades == [trade]
    assert seen_trades[0] is trade
    assert (
        trade.direction,
        trade.entry_price,
        trade.stop_loss_price,
        trade.take_profit_price,
    ) == original_values
    assert result.trade_validation is validation
    assert {field.name for field in fields(result)} == {
        "market_structure",
        "liquidity_sweeps",
        "trade_validation",
    }
    assert not hasattr(result, "recommendation")


def test_repeated_identical_inputs_produce_deterministic_results() -> None:
    bars = candles_with_high_sweep()
    trade = valid_trade()

    first = analyze_market_and_trade(bars, trade)
    second = analyze_market_and_trade(bars, trade)

    assert first == second
