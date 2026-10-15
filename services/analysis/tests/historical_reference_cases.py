"""Small, independently labelled synthetic cases for historical evaluation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tradiopro_analysis.liquidity_sweeps import (
    LiquiditySweepEvent,
    LiquiditySweepKind,
)
from tradiopro_analysis.market_structure import (
    Candle,
    Direction,
    EventKind,
    StructureEvent,
    Swing,
    SwingKind,
    TrendState,
)


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    instrument: str
    timeframe: str
    source: str
    candles: tuple[Candle, ...]
    expected_swings: tuple[Swing, ...]
    expected_structure_events: tuple[StructureEvent, ...]
    expected_sweeps: tuple[LiquiditySweepEvent, ...]
    expected_trend: TrendState


_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _at_minute(index: int) -> datetime:
    return _START + timedelta(minutes=index)


# At pivot index 2, high 15 is above highs 12, 13, 14, and 13; low 6 is
# below lows 8, 7, 9, and 8. Both pivots therefore confirm at index 4.
# Existing levels are processed before that confirmation on candle 4, so
# neither can cause an event then. Candle 5 is their first eligible candle:
# its high 16 penetrates 15 but its close 14 rejects below it, making one
# bearish high-side sweep without a close-confirmed structure break.
SYNTHETIC_HIGH_SWEEP: EvaluationCase = EvaluationCase(
    case_id="synthetic-confirmed-pivots-high-sweep",
    instrument="SYNTHETIC",
    timeframe="1m",
    source="Manually specified synthetic OHLCV; not historical market data.",
    candles=(
        Candle(_at_minute(0), 10, 12, 8, 10, 100),
        Candle(_at_minute(1), 10, 13, 7, 11, 100),
        Candle(_at_minute(2), 14, 15, 6, 14, 100),
        Candle(_at_minute(3), 10, 14, 9, 10, 100),
        Candle(_at_minute(4), 9, 13, 8, 10, 100),
        Candle(_at_minute(5), 14, 16, 11, 14, 100),
    ),
    expected_swings=(
        Swing(
            kind=SwingKind.HIGH,
            index=2,
            timestamp=_at_minute(2),
            price=15,
            label=None,
            confirmed_at_index=4,
            confirmed_at=_at_minute(4),
        ),
        Swing(
            kind=SwingKind.LOW,
            index=2,
            timestamp=_at_minute(2),
            price=6,
            label=None,
            confirmed_at_index=4,
            confirmed_at=_at_minute(4),
        ),
    ),
    expected_structure_events=(
        StructureEvent(
            kind=EventKind.WICK_PENETRATION,
            direction=Direction.BULLISH,
            index=5,
            timestamp=_at_minute(5),
            level_price=15,
            level_index=2,
        ),
    ),
    expected_sweeps=(
        LiquiditySweepEvent(
            kind=LiquiditySweepKind.LIQUIDITY_SWEEP,
            direction=Direction.BEARISH,
            index=5,
            timestamp=_at_minute(5),
            swing_kind=SwingKind.HIGH,
            swing_index=2,
            swing_price=15,
            penetration_price=16,
            rejection_close=14,
        ),
    ),
    expected_trend=TrendState.UNINITIALIZED,
)


# At pivot index 2, low 5 is below lows 8, 7, 6, and 7, so it confirms at 4.
# Candle 5 is the first eligible candle: low 3 penetrates 5 and close 6
# rejects above it. Its close does not break the low, so trend stays
# uninitialized; the only structural event is the wick penetration.
SYNTHETIC_LOW_SWEEP: EvaluationCase = EvaluationCase(
    case_id="synthetic-confirmed-pivot-low-sweep",
    instrument="SYNTHETIC",
    timeframe="1m",
    source="Manually specified synthetic OHLCV; not historical market data.",
    candles=(
        Candle(_at_minute(0), 10, 12, 8, 10, 100),
        Candle(_at_minute(1), 12, 13, 7, 12, 100),
        Candle(_at_minute(2), 6, 11, 5, 6, 100),
        Candle(_at_minute(3), 7, 12, 6, 7, 100),
        Candle(_at_minute(4), 8, 10, 7, 8, 100),
        Candle(_at_minute(5), 6, 7, 3, 6, 100),
    ),
    expected_swings=(
        Swing(
            kind=SwingKind.LOW,
            index=2,
            timestamp=_at_minute(2),
            price=5,
            label=None,
            confirmed_at_index=4,
            confirmed_at=_at_minute(4),
        ),
    ),
    expected_structure_events=(
        StructureEvent(
            kind=EventKind.WICK_PENETRATION,
            direction=Direction.BEARISH,
            index=5,
            timestamp=_at_minute(5),
            level_price=5,
            level_index=2,
        ),
    ),
    expected_sweeps=(
        LiquiditySweepEvent(
            kind=LiquiditySweepKind.LIQUIDITY_SWEEP,
            direction=Direction.BULLISH,
            index=5,
            timestamp=_at_minute(5),
            swing_kind=SwingKind.LOW,
            swing_index=2,
            swing_price=5,
            penetration_price=3,
            rejection_close=6,
        ),
    ),
    expected_trend=TrendState.UNINITIALIZED,
)


REFERENCE_CASES: tuple[EvaluationCase, ...] = (
    SYNTHETIC_HIGH_SWEEP,
    SYNTHETIC_LOW_SWEEP,
)
