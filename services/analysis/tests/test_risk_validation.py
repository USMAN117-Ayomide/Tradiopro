import math

import pytest

from tradiopro_analysis.risk_validation import (
    ProposedTrade,
    TradeDirection,
    TradeField,
    TradeValidationCode,
    TradeValidationError,
    TradeValidationResult,
    validate_trade_geometry,
)


def assert_result_invariant(result: TradeValidationResult) -> None:
    if result.is_valid:
        assert result.errors == ()
        assert result.risk_distance is not None
        assert result.reward_distance is not None
        assert result.reward_to_risk_ratio is not None
        assert all(
            math.isfinite(metric)
            for metric in (
                result.risk_distance,
                result.reward_distance,
                result.reward_to_risk_ratio,
            )
        )
    else:
        assert result.errors
        assert result.risk_distance is None
        assert result.reward_distance is None
        assert result.reward_to_risk_ratio is None


@pytest.mark.parametrize(
    ("trade", "expected"),
    [
        (
            ProposedTrade("long", 100, 95, 110),
            (5.0, 10.0, 2.0),
        ),
        (
            ProposedTrade(TradeDirection.SHORT, 100, 105, 90),
            (5.0, 10.0, 2.0),
        ),
    ],
)
def test_valid_trade_calculates_directional_distances_and_ratio(
    trade: ProposedTrade, expected: tuple[float, float, float]
) -> None:
    result = validate_trade_geometry(trade)

    assert result.is_valid
    assert result.errors == ()
    assert (
        result.risk_distance,
        result.reward_distance,
        result.reward_to_risk_ratio,
    ) == expected
    assert_result_invariant(result)


@pytest.mark.parametrize(
    ("direction", "code"),
    [
        (None, TradeValidationCode.MISSING_VALUE),
        ("", TradeValidationCode.INVALID_DIRECTION),
        ("LONG", TradeValidationCode.INVALID_DIRECTION),
        (1, TradeValidationCode.INVALID_DIRECTION),
        (True, TradeValidationCode.INVALID_DIRECTION),
    ],
)
def test_invalid_direction_returns_machine_readable_error(
    direction: object, code: TradeValidationCode
) -> None:
    result = validate_trade_geometry(ProposedTrade(direction, 100, 95, 110))

    assert TradeValidationError(TradeField.DIRECTION, code) in result.errors
    assert_result_invariant(result)


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        (TradeField.ENTRY_PRICE, {"entry_price": None}),
        (TradeField.STOP_LOSS_PRICE, {"stop_loss_price": None}),
        (TradeField.TAKE_PROFIT_PRICE, {"take_profit_price": None}),
    ],
)
def test_missing_prices_are_reported(
    field: TradeField, kwargs: dict[str, object]
) -> None:
    trade = ProposedTrade(
        direction="long",
        entry_price=kwargs.get("entry_price", 100),
        stop_loss_price=kwargs.get("stop_loss_price", 95),
        take_profit_price=kwargs.get("take_profit_price", 110),
    )
    result = validate_trade_geometry(trade)

    assert TradeValidationError(
        field, TradeValidationCode.MISSING_VALUE
    ) in result.errors
    assert_result_invariant(result)


@pytest.mark.parametrize(
    "field",
    [
        TradeField.ENTRY_PRICE,
        TradeField.STOP_LOSS_PRICE,
        TradeField.TAKE_PROFIT_PRICE,
    ],
)
@pytest.mark.parametrize(
    ("value", "code"),
    [
        (True, TradeValidationCode.BOOLEAN_NOT_ALLOWED),
        (False, TradeValidationCode.BOOLEAN_NOT_ALLOWED),
        ("100", TradeValidationCode.NON_NUMERIC),
        (object(), TradeValidationCode.NON_NUMERIC),
        (float("nan"), TradeValidationCode.NON_FINITE),
        (float("inf"), TradeValidationCode.NON_FINITE),
        (float("-inf"), TradeValidationCode.NON_FINITE),
        (0, TradeValidationCode.NON_POSITIVE),
        (-1.5, TradeValidationCode.NON_POSITIVE),
    ],
)
def test_invalid_prices_are_reported_for_each_price_field(
    field: TradeField, value: object, code: TradeValidationCode
) -> None:
    prices: dict[str, object] = {
        "entry_price": 100,
        "stop_loss_price": 95,
        "take_profit_price": 110,
    }
    prices[field.value] = value
    trade = ProposedTrade(
        direction="long",
        entry_price=prices["entry_price"],
        stop_loss_price=prices["stop_loss_price"],
        take_profit_price=prices["take_profit_price"],
    )
    result = validate_trade_geometry(trade)

    assert TradeValidationError(field, code) in result.errors
    assert_result_invariant(result)


@pytest.mark.parametrize(
    ("trade", "field", "code"),
    [
        (
            ProposedTrade("long", 100, 100, 110),
            TradeField.STOP_LOSS_PRICE,
            TradeValidationCode.ZERO_RISK_DISTANCE,
        ),
        (
            ProposedTrade("long", 100, 95, 100),
            TradeField.TAKE_PROFIT_PRICE,
            TradeValidationCode.ZERO_REWARD_DISTANCE,
        ),
        (
            ProposedTrade("long", 100, 101, 110),
            TradeField.STOP_LOSS_PRICE,
            TradeValidationCode.INVALID_PRICE_ORDER,
        ),
        (
            ProposedTrade("long", 100, 95, 99),
            TradeField.TAKE_PROFIT_PRICE,
            TradeValidationCode.INVALID_PRICE_ORDER,
        ),
        (
            ProposedTrade("short", 100, 100, 90),
            TradeField.STOP_LOSS_PRICE,
            TradeValidationCode.ZERO_RISK_DISTANCE,
        ),
        (
            ProposedTrade("short", 100, 105, 100),
            TradeField.TAKE_PROFIT_PRICE,
            TradeValidationCode.ZERO_REWARD_DISTANCE,
        ),
        (
            ProposedTrade("short", 100, 99, 90),
            TradeField.STOP_LOSS_PRICE,
            TradeValidationCode.INVALID_PRICE_ORDER,
        ),
        (
            ProposedTrade("short", 100, 105, 101),
            TradeField.TAKE_PROFIT_PRICE,
            TradeValidationCode.INVALID_PRICE_ORDER,
        ),
    ],
)
def test_incorrect_price_order_returns_field_specific_error(
    trade: ProposedTrade, field: TradeField, code: TradeValidationCode
) -> None:
    result = validate_trade_geometry(trade)

    assert TradeValidationError(field, code) in result.errors
    assert_result_invariant(result)


def test_unrepresentably_large_integer_is_rejected_without_raising() -> None:
    result = validate_trade_geometry(
        ProposedTrade("long", 10**1000, 1, 10**1001)
    )

    assert TradeValidationError(
        TradeField.ENTRY_PRICE, TradeValidationCode.INTEGER_OUT_OF_FLOAT_RANGE
    ) in result.errors
    assert TradeValidationError(
        TradeField.TAKE_PROFIT_PRICE,
        TradeValidationCode.INTEGER_OUT_OF_FLOAT_RANGE,
    ) in result.errors
    assert_result_invariant(result)


def test_inexact_large_integer_prices_are_rejected_explicitly() -> None:
    base = 2**53
    result = validate_trade_geometry(
        ProposedTrade("long", base + 1, base - 1, base + 3)
    )

    assert TradeValidationError(
        TradeField.ENTRY_PRICE,
        TradeValidationCode.INTEGER_NOT_EXACTLY_REPRESENTABLE,
    ) in result.errors
    assert TradeValidationError(
        TradeField.TAKE_PROFIT_PRICE,
        TradeValidationCode.INTEGER_NOT_EXACTLY_REPRESENTABLE,
    ) in result.errors
    assert_result_invariant(result)


def test_small_integer_prices_produce_correct_metrics() -> None:
    result = validate_trade_geometry(ProposedTrade("long", 100, 95, 110))

    assert result.is_valid
    assert (
        result.risk_distance,
        result.reward_distance,
        result.reward_to_risk_ratio,
    ) == (5.0, 10.0, 2.0)
    assert_result_invariant(result)


def test_exactly_representable_large_integer_prices_are_accepted() -> None:
    base = 2**54
    result = validate_trade_geometry(
        ProposedTrade("long", base + 4, base, base + 8)
    )

    assert result.is_valid
    assert (
        result.risk_distance,
        result.reward_distance,
        result.reward_to_risk_ratio,
    ) == (4.0, 4.0, 1.0)
    assert_result_invariant(result)


def test_large_finite_prices_are_calculated_safely() -> None:
    result = validate_trade_geometry(
        ProposedTrade("long", 1e308, 9e307, 1.7e308)
    )

    assert result.is_valid
    assert result.risk_distance is not None
    assert result.reward_distance is not None
    assert result.reward_to_risk_ratio is not None
    assert_result_invariant(result)


def test_ratio_overflow_is_invalid_and_returns_no_metrics() -> None:
    result = validate_trade_geometry(
        ProposedTrade("long", 1e-300, 5e-324, 1e308)
    )

    assert TradeValidationError(
        TradeField.REWARD_TO_RISK_RATIO,
        TradeValidationCode.ARITHMETIC_OVERFLOW,
    ) in result.errors
    assert_result_invariant(result)


def test_ratio_underflow_is_invalid_and_returns_no_metrics() -> None:
    result = validate_trade_geometry(
        ProposedTrade("short", 1.0, 1e308, math.nextafter(1.0, 0.0))
    )

    assert TradeValidationError(
        TradeField.REWARD_TO_RISK_RATIO,
        TradeValidationCode.REWARD_TO_RISK_UNDERFLOW,
    ) in result.errors
    assert_result_invariant(result)


def test_identical_inputs_produce_deterministic_results() -> None:
    trade = ProposedTrade("short", 100, 105, 90)

    assert validate_trade_geometry(trade) == validate_trade_geometry(trade)


def test_non_proposed_trade_is_programmer_error() -> None:
    with pytest.raises(TypeError, match="ProposedTrade"):
        validate_trade_geometry(object())  # type: ignore[arg-type]
