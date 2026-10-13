"""Deterministic validation of proposed trade price geometry."""

from dataclasses import dataclass
from enum import Enum
import math


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeField(str, Enum):
    DIRECTION = "direction"
    ENTRY_PRICE = "entry_price"
    STOP_LOSS_PRICE = "stop_loss_price"
    TAKE_PROFIT_PRICE = "take_profit_price"
    RISK_DISTANCE = "risk_distance"
    REWARD_DISTANCE = "reward_distance"
    REWARD_TO_RISK_RATIO = "reward_to_risk_ratio"


class TradeValidationCode(str, Enum):
    MISSING_VALUE = "missing_value"
    INVALID_DIRECTION = "invalid_direction"
    BOOLEAN_NOT_ALLOWED = "boolean_not_allowed"
    NON_NUMERIC = "non_numeric"
    NON_FINITE = "non_finite"
    NON_POSITIVE = "non_positive"
    INTEGER_NOT_EXACTLY_REPRESENTABLE = "integer_not_exactly_representable"
    INTEGER_OUT_OF_FLOAT_RANGE = "integer_out_of_float_range"
    ZERO_RISK_DISTANCE = "zero_risk_distance"
    ZERO_REWARD_DISTANCE = "zero_reward_distance"
    INVALID_PRICE_ORDER = "invalid_price_order"
    ARITHMETIC_OVERFLOW = "arithmetic_overflow"
    REWARD_TO_RISK_UNDERFLOW = "reward_to_risk_underflow"


@dataclass(frozen=True, slots=True)
class ProposedTrade:
    direction: TradeDirection | str | None = None
    entry_price: object = None
    stop_loss_price: object = None
    take_profit_price: object = None


@dataclass(frozen=True, slots=True)
class TradeValidationError:
    field: TradeField
    code: TradeValidationCode


@dataclass(frozen=True, slots=True)
class TradeValidationResult:
    is_valid: bool
    errors: tuple[TradeValidationError, ...]
    risk_distance: float | None
    reward_distance: float | None
    reward_to_risk_ratio: float | None


def _normalize_price(
    value: object, field: TradeField
) -> tuple[float | None, TradeValidationError | None]:
    if value is None:
        return None, TradeValidationError(field, TradeValidationCode.MISSING_VALUE)
    if isinstance(value, bool):
        return None, TradeValidationError(
            field, TradeValidationCode.BOOLEAN_NOT_ALLOWED
        )
    if not isinstance(value, (int, float)):
        return None, TradeValidationError(field, TradeValidationCode.NON_NUMERIC)

    try:
        normalized = float(value)
    except OverflowError:
        code = (
            TradeValidationCode.INTEGER_OUT_OF_FLOAT_RANGE
            if isinstance(value, int)
            else TradeValidationCode.NON_FINITE
        )
        return None, TradeValidationError(field, code)
    except (TypeError, ValueError):
        return None, TradeValidationError(field, TradeValidationCode.NON_FINITE)

    if not math.isfinite(normalized):
        return None, TradeValidationError(field, TradeValidationCode.NON_FINITE)
    if isinstance(value, int) and int(normalized) != value:
        return None, TradeValidationError(
            field, TradeValidationCode.INTEGER_NOT_EXACTLY_REPRESENTABLE
        )
    if normalized <= 0:
        return None, TradeValidationError(field, TradeValidationCode.NON_POSITIVE)
    return normalized, None


def _invalid_result(
    errors: list[TradeValidationError],
) -> TradeValidationResult:
    return TradeValidationResult(
        is_valid=False,
        errors=tuple(errors),
        risk_distance=None,
        reward_distance=None,
        reward_to_risk_ratio=None,
    )


def validate_trade_geometry(trade: ProposedTrade) -> TradeValidationResult:
    """Validate direction-specific price ordering and calculate distances."""
    if not isinstance(trade, ProposedTrade):
        raise TypeError("trade must be a ProposedTrade")

    errors: list[TradeValidationError] = []
    direction: TradeDirection | None
    if trade.direction is None:
        direction = None
        errors.append(
            TradeValidationError(
                TradeField.DIRECTION, TradeValidationCode.MISSING_VALUE
            )
        )
    elif isinstance(trade.direction, TradeDirection):
        direction = trade.direction
    elif type(trade.direction) is str:
        try:
            direction = TradeDirection(trade.direction)
        except ValueError:
            direction = None
            errors.append(
                TradeValidationError(
                    TradeField.DIRECTION, TradeValidationCode.INVALID_DIRECTION
                )
            )
    else:
        direction = None
        errors.append(
            TradeValidationError(
                TradeField.DIRECTION, TradeValidationCode.INVALID_DIRECTION
            )
        )

    entry, error = _normalize_price(trade.entry_price, TradeField.ENTRY_PRICE)
    if error is not None:
        errors.append(error)
    stop, error = _normalize_price(
        trade.stop_loss_price, TradeField.STOP_LOSS_PRICE
    )
    if error is not None:
        errors.append(error)
    target, error = _normalize_price(
        trade.take_profit_price, TradeField.TAKE_PROFIT_PRICE
    )
    if error is not None:
        errors.append(error)

    if direction is not None and entry is not None:
        if stop is not None:
            if direction is TradeDirection.LONG and stop >= entry:
                code = (
                    TradeValidationCode.ZERO_RISK_DISTANCE
                    if stop == entry
                    else TradeValidationCode.INVALID_PRICE_ORDER
                )
                errors.append(TradeValidationError(TradeField.STOP_LOSS_PRICE, code))
            elif direction is TradeDirection.SHORT and stop <= entry:
                code = (
                    TradeValidationCode.ZERO_RISK_DISTANCE
                    if stop == entry
                    else TradeValidationCode.INVALID_PRICE_ORDER
                )
                errors.append(TradeValidationError(TradeField.STOP_LOSS_PRICE, code))

        if target is not None:
            if direction is TradeDirection.LONG and target <= entry:
                code = (
                    TradeValidationCode.ZERO_REWARD_DISTANCE
                    if target == entry
                    else TradeValidationCode.INVALID_PRICE_ORDER
                )
                errors.append(
                    TradeValidationError(TradeField.TAKE_PROFIT_PRICE, code)
                )
            elif direction is TradeDirection.SHORT and target >= entry:
                code = (
                    TradeValidationCode.ZERO_REWARD_DISTANCE
                    if target == entry
                    else TradeValidationCode.INVALID_PRICE_ORDER
                )
                errors.append(
                    TradeValidationError(TradeField.TAKE_PROFIT_PRICE, code)
                )

    if errors:
        return _invalid_result(errors)

    if direction is TradeDirection.LONG:
        risk_distance = entry - stop
        reward_distance = target - entry
    else:
        risk_distance = stop - entry
        reward_distance = entry - target
    reward_to_risk_ratio = reward_distance / risk_distance

    if reward_to_risk_ratio == 0.0:
        errors.append(
            TradeValidationError(
                TradeField.REWARD_TO_RISK_RATIO,
                TradeValidationCode.REWARD_TO_RISK_UNDERFLOW,
            )
        )
    derived_values = (
        (TradeField.RISK_DISTANCE, risk_distance),
        (TradeField.REWARD_DISTANCE, reward_distance),
        (TradeField.REWARD_TO_RISK_RATIO, reward_to_risk_ratio),
    )
    for field, value in derived_values:
        if not math.isfinite(value):
            errors.append(
                TradeValidationError(
                    field, TradeValidationCode.ARITHMETIC_OVERFLOW
                )
            )
    if errors:
        return _invalid_result(errors)

    return TradeValidationResult(
        is_valid=True,
        errors=(),
        risk_distance=risk_distance,
        reward_distance=reward_distance,
        reward_to_risk_ratio=reward_to_risk_ratio,
    )
