"""Deterministic, same-candle liquidity-sweep detection.

Pass the candles and AnalysisResult produced by analyze_market_structure for
those candles. A swing becomes eligible on the candle after its confirmation
candle. Only the latest confirmed swing of each kind is monitored; structural
break events consume levels using the same swing identity as market structure.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Sequence

from .market_structure import (
    AnalysisResult,
    Candle,
    Direction,
    EventKind,
    Swing,
    SwingKind,
    StructureEvent,
    _validate_candles,
)


class LiquiditySweepKind(str, Enum):
    LIQUIDITY_SWEEP = "liquidity_sweep"


@dataclass(frozen=True, slots=True)
class LiquiditySweepEvent:
    kind: LiquiditySweepKind
    direction: Direction
    index: int
    timestamp: datetime
    swing_kind: SwingKind
    swing_index: int
    swing_price: float
    penetration_price: float
    rejection_close: float


def _validate_analysis(candles: Sequence[Candle], analysis: AnalysisResult) -> None:
    """Reject inconsistent structural events before they affect level state."""
    if not isinstance(analysis, AnalysisResult):
        raise TypeError("analysis must be an AnalysisResult")

    seen_swings: set[tuple[SwingKind, int]] = set()
    swings_by_identity: dict[tuple[SwingKind, int], Swing] = {}
    for swing in analysis.swings:
        if not isinstance(swing, Swing):
            raise TypeError("analysis swings must contain Swing instances")
        if not isinstance(swing.kind, SwingKind):
            raise TypeError("swing kind must be a SwingKind")
        if (
            isinstance(swing.index, bool)
            or not isinstance(swing.index, int)
            or swing.index < 2
            or swing.index >= len(candles)
        ):
            raise ValueError("swing pivot index is outside the candle sequence")
        if (
            isinstance(swing.confirmed_at_index, bool)
            or not isinstance(swing.confirmed_at_index, int)
            or swing.confirmed_at_index < swing.index + 2
        ):
            raise ValueError("swing confirmation index must be at least pivot + 2")
        if (
            isinstance(swing.price, bool)
            or not isinstance(swing.price, (int, float))
            or not math.isfinite(swing.price)
            or swing.price <= 0
        ):
            raise ValueError("swing price must be a finite positive number")
        if not isinstance(swing.timestamp, datetime):
            raise TypeError("swing timestamp must be a datetime")
        if (
            swing.timestamp.tzinfo is None
            or swing.timestamp.utcoffset() is None
            or swing.timestamp != candles[swing.index].timestamp
        ):
            raise ValueError("swing timestamp must match its pivot candle")

        pivot_price = (
            candles[swing.index].high
            if swing.kind is SwingKind.HIGH
            else candles[swing.index].low
        )
        if swing.price != pivot_price:
            raise ValueError("swing price must match its pivot candle")

        identity = (swing.kind, swing.index)
        if identity in seen_swings:
            raise ValueError("duplicate swing identity")
        seen_swings.add(identity)
        swings_by_identity[identity] = swing

        if not isinstance(swing.confirmed_at, datetime):
            raise TypeError("swing confirmation timestamp must be a datetime")
        if (
            swing.confirmed_at.tzinfo is None
            or swing.confirmed_at.utcoffset() is None
        ):
            raise ValueError("swing confirmation timestamp must include a timezone")
        if swing.confirmed_at_index < len(candles):
            if swing.confirmed_at != candles[swing.confirmed_at_index].timestamp:
                raise ValueError(
                    "swing confirmation timestamp must match its confirmation candle"
                )
        elif swing.confirmed_at <= swing.timestamp:
            raise ValueError("swing confirmation must follow its pivot timestamp")

    events_by_index: dict[int, list[StructureEvent]] = {}
    previous_index = -1
    for event in analysis.events:
        if not isinstance(event, StructureEvent):
            raise TypeError("analysis events must contain StructureEvent instances")
        if not isinstance(event.kind, EventKind):
            raise TypeError("event kind must be an EventKind")
        if (
            isinstance(event.index, bool)
            or not isinstance(event.index, int)
            or event.index < 0
            or event.index >= len(candles)
        ):
            raise ValueError("analysis event index is outside the candle sequence")
        if event.index < previous_index:
            raise ValueError("analysis events must be in chronological order")
        previous_index = event.index
        if event.timestamp != candles[event.index].timestamp:
            raise ValueError("analysis event timestamp must match its candle")
        events_by_index.setdefault(event.index, []).append(event)

    consumed: set[tuple[SwingKind, int]] = set()
    for index, events in events_by_index.items():
        active: dict[SwingKind, Swing] = {}
        for swing in analysis.swings:
            if swing.confirmed_at_index < index:
                current = active.get(swing.kind)
                if current is None or (
                    swing.confirmed_at_index,
                    swing.index,
                ) > (current.confirmed_at_index, current.index):
                    active[swing.kind] = swing

        ambiguous_events = [
            event for event in events if event.kind is EventKind.AMBIGUOUS_BREAK
        ]
        if ambiguous_events:
            if len(ambiguous_events) != 1 or len(
                [event for event in events if event.kind is not EventKind.WICK_PENETRATION]
            ) != 1:
                raise ValueError("ambiguous event cannot coexist with another break")
            event = ambiguous_events[0]
            if (
                event.direction is not None
                or event.level_index is not None
                or event.level_price is not None
            ):
                raise ValueError("ambiguous events cannot identify a direction or level")
            active_high = active.get(SwingKind.HIGH)
            active_low = active.get(SwingKind.LOW)
            candle = candles[index]
            if (
                active_high is None
                or active_low is None
                or (SwingKind.HIGH, active_high.index) in consumed
                or (SwingKind.LOW, active_low.index) in consumed
                or not (
                    candle.close > active_high.price
                    and candle.close < active_low.price
                )
            ):
                raise ValueError(
                    "ambiguous event requires opposing close breaks of eligible active swings"
                )

            for wick_event in events:
                if wick_event.kind is EventKind.WICK_PENETRATION:
                    _validate_directional_event(
                        wick_event, index, candles, swings_by_identity, active, consumed
                    )
            consumed.add((SwingKind.HIGH, active_high.index))
            consumed.add((SwingKind.LOW, active_low.index))
            continue

        consuming: set[tuple[SwingKind, int]] = set()
        for event in events:
            if event.kind not in {
                EventKind.BOS,
                EventKind.CHOCH,
                EventKind.UNRESOLVED_BREAK,
                EventKind.WICK_PENETRATION,
            }:
                raise ValueError("unsupported structural event kind")
            identity = _validate_directional_event(
                event, index, candles, swings_by_identity, active, consumed
            )
            if event.kind is not EventKind.WICK_PENETRATION:
                if identity in consuming:
                    raise ValueError("multiple break events consume the same swing")
                consuming.add(identity)
        consumed.update(consuming)


def _validate_directional_event(
    event: StructureEvent,
    index: int,
    candles: Sequence[Candle],
    swings_by_identity: dict[tuple[SwingKind, int], Swing],
    active: dict[SwingKind, Swing],
    consumed: set[tuple[SwingKind, int]],
) -> tuple[SwingKind, int]:
    if not isinstance(event.direction, Direction):
        raise ValueError("directional events must identify a valid direction")
    if (
        isinstance(event.level_index, bool)
        or not isinstance(event.level_index, int)
        or event.level_price is None
        or isinstance(event.level_price, bool)
        or not isinstance(event.level_price, (int, float))
        or not math.isfinite(event.level_price)
    ):
        raise ValueError("directional events must identify a finite swing level")

    kind = (
        SwingKind.HIGH
        if event.direction is Direction.BULLISH
        else SwingKind.LOW
    )
    identity = (kind, event.level_index)
    swing = swings_by_identity.get(identity)
    if swing is None:
        raise ValueError("structural event references an unknown swing identity")
    if swing.confirmed_at_index >= index:
        raise ValueError("structural event references a swing not yet eligible")
    if event.level_price != swing.price:
        raise ValueError("structural event level price does not match its swing")
    if active.get(kind) is not swing:
        raise ValueError("structural event does not reference the active swing")
    if identity in consumed:
        raise ValueError("structural event references an already consumed swing")

    candle = candles[index]
    if event.kind is EventKind.WICK_PENETRATION:
        penetrated = (
            candle.high > swing.price
            if event.direction is Direction.BULLISH
            else candle.low < swing.price
        )
        if not penetrated:
            raise ValueError("wick event is not supported by its candle")
    else:
        broken = (
            candle.close > swing.price
            if event.direction is Direction.BULLISH
            else candle.close < swing.price
        )
        if not broken:
            raise ValueError("break event is not supported by its candle close")

    return identity


def detect_liquidity_sweeps(
    candles: Sequence[Candle],
    analysis: AnalysisResult,
) -> tuple[LiquiditySweepEvent, ...]:
    """Return completed same-candle sweeps against eligible confirmed swings.

    ``analysis`` should be the result of ``analyze_market_structure(candles)``.
    Swing metadata allows the detector to enforce pivot/confirmation timing;
    structural break events identify consumed levels and ambiguous candles.
    """
    _validate_candles(candles)
    _validate_analysis(candles, analysis)

    swings_by_activation: dict[int, list[Swing]] = {}
    for swing in analysis.swings:
        activation_index = swing.confirmed_at_index + 1
        swings_by_activation.setdefault(activation_index, []).append(swing)
    for swings in swings_by_activation.values():
        swings.sort(key=lambda swing: (swing.index, swing.kind.value))

    events_by_index: dict[int, list[StructureEvent]] = {}
    for event in analysis.events:
        events_by_index.setdefault(event.index, []).append(event)

    latest: dict[SwingKind, Swing] = {}
    consumed: set[tuple[SwingKind, int]] = set()
    swept: set[tuple[SwingKind, int]] = set()
    result: list[LiquiditySweepEvent] = []

    for index, candle in enumerate(candles):
        for swing in swings_by_activation.get(index, ()):
            latest[swing.kind] = swing

        structural_events = events_by_index.get(index, ())
        ambiguous = any(
            event.kind is EventKind.AMBIGUOUS_BREAK
            for event in structural_events
        )
        if ambiguous:
            for kind in (SwingKind.HIGH, SwingKind.LOW):
                active = latest.get(kind)
                if active is not None:
                    consumed.add((kind, active.index))
        else:
            for event in structural_events:
                if event.kind not in {
                    EventKind.BOS,
                    EventKind.CHOCH,
                    EventKind.UNRESOLVED_BREAK,
                }:
                    continue
                if event.level_index is None or event.direction is None:
                    continue
                kind = (
                    SwingKind.HIGH
                    if event.direction is Direction.BULLISH
                    else SwingKind.LOW
                )
                consumed.add((kind, event.level_index))

        if ambiguous:
            continue

        active_high = latest.get(SwingKind.HIGH)
        active_low = latest.get(SwingKind.LOW)
        high_identity = (
            (SwingKind.HIGH, active_high.index)
            if active_high is not None
            else None
        )
        low_identity = (
            (SwingKind.LOW, active_low.index)
            if active_low is not None
            else None
        )

        high_sweep = (
            active_high is not None
            and high_identity not in consumed
            and high_identity not in swept
            and candle.high > active_high.price
            and candle.close < active_high.price
        )
        low_sweep = (
            active_low is not None
            and low_identity not in consumed
            and low_identity not in swept
            and candle.low < active_low.price
            and candle.close > active_low.price
        )

        if high_sweep and active_high is not None and high_identity is not None:
            result.append(
                LiquiditySweepEvent(
                    kind=LiquiditySweepKind.LIQUIDITY_SWEEP,
                    direction=Direction.BEARISH,
                    index=index,
                    timestamp=candle.timestamp,
                    swing_kind=SwingKind.HIGH,
                    swing_index=active_high.index,
                    swing_price=active_high.price,
                    penetration_price=candle.high,
                    rejection_close=candle.close,
                )
            )
            swept.add(high_identity)

        if low_sweep and active_low is not None and low_identity is not None:
            result.append(
                LiquiditySweepEvent(
                    kind=LiquiditySweepKind.LIQUIDITY_SWEEP,
                    direction=Direction.BULLISH,
                    index=index,
                    timestamp=candle.timestamp,
                    swing_kind=SwingKind.LOW,
                    swing_index=active_low.index,
                    swing_price=active_low.price,
                    penetration_price=candle.low,
                    rejection_close=candle.close,
                )
            )
            swept.add(low_identity)

    return tuple(result)
