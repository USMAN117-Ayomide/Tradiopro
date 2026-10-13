"""Deterministic swing and close-based market-structure analysis.

Prices are compared exactly; callers should normalize prices to the instrument's
tick size before analysis if decimal tick semantics are required.

The latest confirmed swing of each type is its active structural level. A level
can produce one close-confirmed break per analysis run. The first directional
break establishes trend and is a BOS; a break against established trend is a
CHoCH and immediately establishes the new direction. Consumption is tracked per
swing identity, not per price. An inverted pair of active levels that would
make both directions break on one close is reported as ambiguous, not guessed.
After that, one-sided breaks are unresolved and consume the broken swing, while
trend remains ambiguous for the rest of the analysis run.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Sequence


class SwingKind(str, Enum):
    HIGH = "high"
    LOW = "low"


class StructureLabel(str, Enum):
    HH = "HH"
    LH = "LH"
    EQH = "EQH"
    HL = "HL"
    LL = "LL"
    EQL = "EQL"


class TrendState(str, Enum):
    UNINITIALIZED = "uninitialized"
    BULLISH = "bullish"
    BEARISH = "bearish"
    AMBIGUOUS = "ambiguous"


class EventKind(str, Enum):
    BOS = "BOS"
    CHOCH = "CHoCH"
    WICK_PENETRATION = "wick_penetration"
    AMBIGUOUS_BREAK = "ambiguous_break"
    UNRESOLVED_BREAK = "unresolved_break"


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Swing:
    kind: SwingKind
    index: int
    timestamp: datetime
    price: float
    label: StructureLabel | None
    confirmed_at_index: int
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class StructureEvent:
    kind: EventKind
    direction: Direction | None
    index: int
    timestamp: datetime
    level_price: float | None
    level_index: int | None


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    swings: tuple[Swing, ...]
    events: tuple[StructureEvent, ...]
    trend: TrendState


def _validate_candles(candles: Sequence[Candle]) -> None:
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise TypeError("candles must be a sequence of Candle instances")
    if len(candles) < 5:
        raise ValueError("at least five candles are required to confirm a swing")

    previous_timestamp: datetime | None = None
    for index, candle in enumerate(candles):
        if not isinstance(candle, Candle):
            raise TypeError(f"candles[{index}] must be a Candle")
        if not isinstance(candle.timestamp, datetime):
            raise TypeError(f"candles[{index}].timestamp must be a datetime")
        if (
            candle.timestamp.tzinfo is None
            or candle.timestamp.utcoffset() is None
        ):
            raise ValueError(f"candles[{index}].timestamp must include a timezone")
        if previous_timestamp is not None and candle.timestamp <= previous_timestamp:
            raise ValueError("candle timestamps must be strictly increasing")
        previous_timestamp = candle.timestamp

        for field in ("open", "high", "low", "close", "volume"):
            value = getattr(candle, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"candles[{index}].{field} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"candles[{index}].{field} must be finite")

        if min(candle.open, candle.high, candle.low, candle.close) <= 0:
            raise ValueError(f"candles[{index}] prices must be positive")
        if candle.volume < 0:
            raise ValueError(f"candles[{index}].volume cannot be negative")
        if candle.low > min(candle.open, candle.close):
            raise ValueError(f"candles[{index}].low exceeds open or close")
        if candle.high < max(candle.open, candle.close):
            raise ValueError(f"candles[{index}].high is below open or close")
        if candle.low > candle.high:
            raise ValueError(f"candles[{index}].low exceeds high")


def _process_active_levels(
    index: int,
    candle: Candle,
    active_high: Swing | None,
    active_low: Swing | None,
    broken_levels: set[tuple[SwingKind, int]],
    trend: TrendState,
) -> tuple[list[StructureEvent], TrendState]:
    high_available = (
        active_high is not None
        and (SwingKind.HIGH, active_high.index) not in broken_levels
    )
    low_available = (
        active_low is not None
        and (SwingKind.LOW, active_low.index) not in broken_levels
    )
    bullish_close_break = (
        high_available
        and active_high is not None
        and candle.close > active_high.price
    )
    bearish_close_break = (
        low_available
        and active_low is not None
        and candle.close < active_low.price
    )
    events: list[StructureEvent] = []

    if (
        high_available
        and active_high is not None
        and candle.high > active_high.price
    ):
        events.append(
            StructureEvent(
                kind=EventKind.WICK_PENETRATION,
                direction=Direction.BULLISH,
                index=index,
                timestamp=candle.timestamp,
                level_price=active_high.price,
                level_index=active_high.index,
            )
        )
    if (
        low_available
        and active_low is not None
        and candle.low < active_low.price
    ):
        events.append(
            StructureEvent(
                kind=EventKind.WICK_PENETRATION,
                direction=Direction.BEARISH,
                index=index,
                timestamp=candle.timestamp,
                level_price=active_low.price,
                level_index=active_low.index,
            )
        )

    if bullish_close_break and bearish_close_break:
        events.append(
            StructureEvent(
                kind=EventKind.AMBIGUOUS_BREAK,
                direction=None,
                index=index,
                timestamp=candle.timestamp,
                level_price=None,
                level_index=None,
            )
        )
        if active_high is not None:
            broken_levels.add((SwingKind.HIGH, active_high.index))
        if active_low is not None:
            broken_levels.add((SwingKind.LOW, active_low.index))
        return events, TrendState.AMBIGUOUS

    if bullish_close_break and active_high is not None:
        if trend is TrendState.AMBIGUOUS:
            event_kind = EventKind.UNRESOLVED_BREAK
        else:
            event_kind = (
                EventKind.CHOCH
                if trend is TrendState.BEARISH
                else EventKind.BOS
            )
        events.append(
            StructureEvent(
                kind=event_kind,
                direction=Direction.BULLISH,
                index=index,
                timestamp=candle.timestamp,
                level_price=active_high.price,
                level_index=active_high.index,
            )
        )
        broken_levels.add((SwingKind.HIGH, active_high.index))
        if trend is not TrendState.AMBIGUOUS:
            trend = TrendState.BULLISH
    elif bearish_close_break and active_low is not None:
        if trend is TrendState.AMBIGUOUS:
            event_kind = EventKind.UNRESOLVED_BREAK
        else:
            event_kind = (
                EventKind.CHOCH
                if trend is TrendState.BULLISH
                else EventKind.BOS
            )
        events.append(
            StructureEvent(
                kind=event_kind,
                direction=Direction.BEARISH,
                index=index,
                timestamp=candle.timestamp,
                level_price=active_low.price,
                level_index=active_low.index,
            )
        )
        broken_levels.add((SwingKind.LOW, active_low.index))
        if trend is not TrendState.AMBIGUOUS:
            trend = TrendState.BEARISH

    return events, trend


def analyze_market_structure(candles: Sequence[Candle]) -> AnalysisResult:
    """Analyze chronological candles without using a pivot before confirmation.

    A pivot at index ``p`` is confirmed only when candle ``p + 2`` has closed.
    On that confirmation candle, existing levels are evaluated first, so the
    same close cannot both confirm and break the newly confirmed pivot.
    """
    _validate_candles(candles)

    swings: list[Swing] = []
    events: list[StructureEvent] = []
    latest: dict[SwingKind, Swing] = {}
    broken_levels: set[tuple[SwingKind, int]] = set()
    trend = TrendState.UNINITIALIZED

    for index, candle in enumerate(candles):
        active_high = latest.get(SwingKind.HIGH)
        active_low = latest.get(SwingKind.LOW)
        level_events, trend = _process_active_levels(
            index,
            candle,
            active_high,
            active_low,
            broken_levels,
            trend,
        )
        events.extend(level_events)

        pivot_index = index - 2
        if pivot_index < 2:
            continue

        left = candles[pivot_index - 2 : pivot_index]
        right = candles[pivot_index + 1 : pivot_index + 3]
        pivot = candles[pivot_index]

        if all(pivot.high > item.high for item in (*left, *right)):
            prior = latest.get(SwingKind.HIGH)
            label = None
            if prior is not None:
                label = (
                    StructureLabel.HH
                    if pivot.high > prior.price
                    else StructureLabel.LH
                    if pivot.high < prior.price
                    else StructureLabel.EQH
                )
            swing = Swing(
                kind=SwingKind.HIGH,
                index=pivot_index,
                timestamp=pivot.timestamp,
                price=pivot.high,
                label=label,
                confirmed_at_index=index,
                confirmed_at=candle.timestamp,
            )
            swings.append(swing)
            latest[SwingKind.HIGH] = swing

        if all(pivot.low < item.low for item in (*left, *right)):
            prior = latest.get(SwingKind.LOW)
            label = None
            if prior is not None:
                label = (
                    StructureLabel.HL
                    if pivot.low > prior.price
                    else StructureLabel.LL
                    if pivot.low < prior.price
                    else StructureLabel.EQL
                )
            swing = Swing(
                kind=SwingKind.LOW,
                index=pivot_index,
                timestamp=pivot.timestamp,
                price=pivot.low,
                label=label,
                confirmed_at_index=index,
                confirmed_at=candle.timestamp,
            )
            swings.append(swing)
            latest[SwingKind.LOW] = swing

    return AnalysisResult(
        swings=tuple(swings),
        events=tuple(events),
        trend=trend,
    )
