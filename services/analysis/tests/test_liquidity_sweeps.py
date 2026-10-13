from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tradiopro_analysis.liquidity_sweeps import (
    LiquiditySweepKind,
    detect_liquidity_sweeps,
)
from tradiopro_analysis.market_structure import (
    AnalysisResult,
    Candle,
    Direction,
    EventKind,
    StructureEvent,
    Swing,
    SwingKind,
    TrendState,
    analyze_market_structure,
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


def high_swing_analysis(
    bars: list[Candle], *, pivot_index: int = 2, price: float = 15
) -> AnalysisResult:
    bars[pivot_index] = replace(bars[pivot_index], high=price)
    return analyze_market_structure(bars)


def low_swing_analysis(
    bars: list[Candle], *, pivot_index: int = 2, price: float = 5
) -> AnalysisResult:
    bars[pivot_index] = replace(bars[pivot_index], low=price)
    return analyze_market_structure(bars)


def swing(
    bars: list[Candle],
    kind: SwingKind,
    pivot_index: int,
    price: float,
    confirmed_at_index: int,
) -> Swing:
    return Swing(
        kind=kind,
        index=pivot_index,
        timestamp=bars[pivot_index].timestamp,
        price=price,
        label=None,
        confirmed_at_index=confirmed_at_index,
        confirmed_at=(
            bars[confirmed_at_index].timestamp
            if confirmed_at_index < len(bars)
            else bars[-1].timestamp + timedelta(minutes=1)
        ),
    )


def supplied_analysis(
    swings: tuple[Swing, ...],
    events: tuple[StructureEvent, ...] = (),
) -> AnalysisResult:
    return AnalysisResult(
        swings=swings,
        events=events,
        trend=TrendState.UNINITIALIZED,
    )


def test_confirmed_swing_high_rejected_on_same_candle_is_bearish_sweep() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=14)
    analysis = analyze_market_structure(bars)

    events = detect_liquidity_sweeps(bars, analysis)

    assert len(events) == 1
    event = events[0]
    assert event.kind is LiquiditySweepKind.LIQUIDITY_SWEEP
    assert event.direction is Direction.BEARISH
    assert (event.index, event.timestamp) == (5, bars[5].timestamp)
    assert (event.swing_kind, event.swing_index, event.swing_price) == (
        SwingKind.HIGH,
        2,
        15,
    )
    assert (event.penetration_price, event.rejection_close) == (16, 14)


def test_confirmed_swing_low_rejected_on_same_candle_is_bullish_sweep() -> None:
    bars = [candle(i) for i in range(9)]
    bars[5] = replace(bars[5], open=6, high=7, low=3, close=6)
    analysis = low_swing_analysis(bars)

    events = detect_liquidity_sweeps(bars, analysis)

    assert len(events) == 1
    assert events[0].direction is Direction.BULLISH
    assert (events[0].swing_kind, events[0].swing_index) == (SwingKind.LOW, 2)
    assert (events[0].swing_price, events[0].penetration_price) == (5, 3)
    assert events[0].rejection_close == 6


@pytest.mark.parametrize(
    ("kind", "bar"),
    [
        (SwingKind.HIGH, candle(5, open_=14, high=16, low=13, close=15)),
        (SwingKind.LOW, candle(5, open_=6, high=7, low=3, close=5)),
    ],
)
def test_penetration_without_strict_rejection_is_not_a_sweep(
    kind: SwingKind, bar: Candle
) -> None:
    bars = [candle(i) for i in range(9)]
    bars[5] = bar
    analysis = (
        high_swing_analysis(bars)
        if kind is SwingKind.HIGH
        else low_swing_analysis(bars)
    )

    assert detect_liquidity_sweeps(bars, analysis) == ()


@pytest.mark.parametrize(
    ("kind", "bar"),
    [
        (SwingKind.HIGH, candle(5, open_=14, high=15, low=13, close=14)),
        (SwingKind.HIGH, candle(5, open_=15, high=16, low=13, close=15)),
        (SwingKind.LOW, candle(5, open_=6, high=7, low=5, close=6)),
        (SwingKind.LOW, candle(5, open_=5, high=7, low=3, close=5)),
    ],
)
def test_equality_at_level_does_not_satisfy_sweep_rules(
    kind: SwingKind, bar: Candle
) -> None:
    bars = [candle(i) for i in range(9)]
    bars[5] = bar
    analysis = (
        high_swing_analysis(bars)
        if kind is SwingKind.HIGH
        else low_swing_analysis(bars)
    )

    assert detect_liquidity_sweeps(bars, analysis) == ()


def test_later_rejection_does_not_complete_earlier_penetration() -> None:
    bars = [candle(i) for i in range(9)]
    bars[5] = candle(5, open_=14, high=16, low=13, close=15)
    bars[6] = candle(6, open_=14, high=14.5, low=13, close=14)
    analysis = high_swing_analysis(bars)

    assert detect_liquidity_sweeps(bars, analysis) == ()


def test_unconfirmed_swing_is_not_eligible() -> None:
    bars = [candle(i) for i in range(6)]
    bars[2] = replace(bars[2], high=15)
    pending = swing(bars, SwingKind.HIGH, 2, 15, 6)

    assert detect_liquidity_sweeps(
        bars, supplied_analysis((pending,))
    ) == ()


def test_swing_is_not_eligible_on_its_confirmation_candle() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15)
    bars[4] = replace(bars[4], open=14, high=16, low=13, close=14)
    confirmed = swing(bars, SwingKind.HIGH, 2, 15, 4)

    assert detect_liquidity_sweeps(
        bars, supplied_analysis((confirmed,))
    ) == ()


def test_repeated_qualifying_candles_sweep_a_swing_only_once() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15)
    for index in (5, 6):
        bars[index] = replace(bars[index], open=14, high=16, low=13, close=14)
    confirmed = swing(bars, SwingKind.HIGH, 2, 15, 4)

    events = detect_liquidity_sweeps(bars, supplied_analysis((confirmed,)))

    assert [event.index for event in events] == [5]


def test_later_equal_price_swing_has_independent_sweep_identity() -> None:
    bars = [candle(i) for i in range(12)]
    for index in (2, 6):
        bars[index] = replace(bars[index], high=15)
    for index in (5, 9):
        bars[index] = replace(bars[index], open=14, high=16, low=13, close=14)
    first = swing(bars, SwingKind.HIGH, 2, 15, 4)
    later = swing(bars, SwingKind.HIGH, 6, 15, 8)

    events = detect_liquidity_sweeps(
        bars, supplied_analysis((first, later))
    )

    assert [
        (event.index, event.swing_kind, event.swing_index, event.swing_price)
        for event in events
    ] == [
        (5, SwingKind.HIGH, 2, 15),
        (9, SwingKind.HIGH, 6, 15),
    ]


def test_both_sweep_directions_can_occur_in_one_valid_sequence() -> None:
    bars = [candle(i) for i in range(10)]
    bars[2] = replace(bars[2], high=15, low=5)
    bars[5] = candle(5, open_=14, high=16, low=13, close=14)
    bars[6] = candle(6, open_=7, high=8, low=3, close=6)
    high = swing(bars, SwingKind.HIGH, 2, 15, 4)
    low = swing(bars, SwingKind.LOW, 2, 5, 4)

    events = detect_liquidity_sweeps(
        bars, supplied_analysis((high, low))
    )

    assert [(event.index, event.direction) for event in events] == [
        (5, Direction.BEARISH),
        (6, Direction.BULLISH),
    ]


def test_both_strict_sweep_conditions_on_one_nonambiguous_candle_emit_both() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15, low=5)
    bars[5] = candle(5, open_=10, high=16, low=3, close=10)
    analysis = analyze_market_structure(bars)

    assert all(
        event.kind is not EventKind.AMBIGUOUS_BREAK
        for event in analysis.events
        if event.index == 5
    )
    events = detect_liquidity_sweeps(bars, analysis)

    assert [(event.direction, event.swing_kind) for event in events] == [
        (Direction.BEARISH, SwingKind.HIGH),
        (Direction.BULLISH, SwingKind.LOW),
    ]


@pytest.mark.parametrize(
    ("event_kind", "direction", "consumed_kind", "remaining_kind", "bar"),
    [
        (
            EventKind.BOS,
            Direction.BULLISH,
            SwingKind.HIGH,
            SwingKind.LOW,
            candle(6, open_=7, high=8, low=3, close=6),
        ),
        (
            EventKind.CHOCH,
            Direction.BEARISH,
            SwingKind.LOW,
            SwingKind.HIGH,
            candle(6, open_=14, high=16, low=13, close=14),
        ),
    ],
)
def test_structural_breaks_consume_levels_without_relabeling_other_sweeps(
    event_kind: EventKind,
    direction: Direction,
    consumed_kind: SwingKind,
    remaining_kind: SwingKind,
    bar: Candle,
) -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15, low=5)
    bars[5] = (
        candle(5, open_=14, high=17, low=13, close=16)
        if direction is Direction.BULLISH
        else candle(5, open_=6, high=8, low=3, close=4)
    )
    bars[6] = bar
    high = swing(bars, SwingKind.HIGH, 2, 15, 4)
    low = swing(bars, SwingKind.LOW, 2, 5, 4)
    structural_event = StructureEvent(
        kind=event_kind,
        direction=direction,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=15 if consumed_kind is SwingKind.HIGH else 5,
        level_index=2,
    )

    events = detect_liquidity_sweeps(
        bars,
        supplied_analysis((high, low), (structural_event,)),
    )

    assert len(events) == 1
    assert events[0].swing_kind is remaining_kind
    assert events[0].kind is LiquiditySweepKind.LIQUIDITY_SWEEP


@pytest.mark.parametrize(
    ("event_kind", "direction", "bar", "include_high"),
    [
        (
            EventKind.UNRESOLVED_BREAK,
            Direction.BULLISH,
            candle(5, open_=14, high=16, low=13, close=16),
            True,
        ),
        (
            EventKind.UNRESOLVED_BREAK,
            Direction.BEARISH,
            candle(5, open_=6, high=7, low=3, close=4),
            False,
        ),
    ],
)
def test_ambiguous_and_unresolved_breaks_do_not_infer_sweeps(
    event_kind: EventKind,
    direction: Direction | None,
    bar: Candle,
    include_high: bool,
) -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15, low=5)
    bars[5] = bar
    swings = []
    if include_high:
        swings.append(swing(bars, SwingKind.HIGH, 2, 15, 4))
    if event_kind is EventKind.AMBIGUOUS_BREAK or direction is Direction.BEARISH:
        swings.append(swing(bars, SwingKind.LOW, 2, 5, 4))
    structural_event = StructureEvent(
        kind=event_kind,
        direction=direction,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=(
            None
            if event_kind is EventKind.AMBIGUOUS_BREAK
            else 15
            if direction is Direction.BULLISH
            else 5
        ),
        level_index=None if event_kind is EventKind.AMBIGUOUS_BREAK else 2,
    )

    assert detect_liquidity_sweeps(
        bars,
        supplied_analysis(tuple(swings), (structural_event,)),
    ) == ()


def test_explicit_ambiguous_event_suppresses_both_sweep_directions() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=10)
    bars[3] = candle(3, open_=13, high=14, low=12, close=13)
    bars[6] = candle(6, open_=11, high=13, low=9, close=11)
    high = swing(bars, SwingKind.HIGH, 2, 10, 4)
    low = swing(bars, SwingKind.LOW, 3, 12, 5)
    ambiguous = StructureEvent(
        kind=EventKind.AMBIGUOUS_BREAK,
        direction=None,
        index=6,
        timestamp=bars[6].timestamp,
        level_price=None,
        level_index=None,
    )

    assert detect_liquidity_sweeps(
        bars,
        supplied_analysis((high, low), (ambiguous,)),
    ) == ()


@pytest.mark.parametrize(
    ("event_kind", "direction", "level_kind", "level_price"),
    [
        (EventKind.BOS, Direction.BULLISH, SwingKind.HIGH, 15),
        (EventKind.CHOCH, Direction.BEARISH, SwingKind.LOW, 5),
        (EventKind.UNRESOLVED_BREAK, Direction.BULLISH, SwingKind.HIGH, 15),
    ],
)
def test_close_break_event_requires_matching_close_predicate(
    event_kind: EventKind,
    direction: Direction,
    level_kind: SwingKind,
    level_price: float,
) -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15, low=5)
    swing_index = 2
    level = swing(bars, level_kind, swing_index, level_price, 4)
    invalid_event = StructureEvent(
        kind=event_kind,
        direction=direction,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=level_price,
        level_index=swing_index,
    )

    with pytest.raises(ValueError, match="not supported by its candle close"):
        detect_liquidity_sweeps(
            bars,
            supplied_analysis((level,), (invalid_event,)),
        )


@pytest.mark.parametrize(
    ("direction", "kind", "price", "bar"),
    [
        (
            Direction.BULLISH,
            SwingKind.HIGH,
            15,
            candle(5, open_=14, high=14.5, low=13, close=14),
        ),
        (
            Direction.BEARISH,
            SwingKind.LOW,
            5,
            candle(5, open_=6, high=7, low=5.5, close=6),
        ),
    ],
)
def test_wick_event_requires_strict_candle_penetration(
    direction: Direction, kind: SwingKind, price: float, bar: Candle
) -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15, low=5)
    bars[5] = bar
    level = swing(bars, kind, 2, price, 4)
    invalid_event = StructureEvent(
        kind=EventKind.WICK_PENETRATION,
        direction=direction,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=price,
        level_index=2,
    )

    with pytest.raises(ValueError, match="wick event is not supported"):
        detect_liquidity_sweeps(
            bars,
            supplied_analysis((level,), (invalid_event,)),
        )


def test_second_break_event_cannot_consume_an_already_consumed_swing() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15)
    bars[5] = candle(5, open_=14, high=17, low=13, close=16)
    bars[6] = candle(6, open_=16, high=18, low=15, close=17)
    level = swing(bars, SwingKind.HIGH, 2, 15, 4)
    first = StructureEvent(
        kind=EventKind.BOS,
        direction=Direction.BULLISH,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=15,
        level_index=2,
    )
    repeated = replace(first, index=6, timestamp=bars[6].timestamp)

    with pytest.raises(ValueError, match="already consumed swing"):
        detect_liquidity_sweeps(
            bars,
            supplied_analysis((level,), (first, repeated)),
        )


def test_malformed_break_cannot_silently_suppress_a_later_valid_sweep() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15)
    bars[6] = candle(6, open_=14, high=16, low=13, close=14)
    high = swing(bars, SwingKind.HIGH, 2, 15, 4)
    unsupported_break = StructureEvent(
        kind=EventKind.BOS,
        direction=Direction.BULLISH,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=15,
        level_index=2,
    )

    with pytest.raises(ValueError, match="not supported by its candle close"):
        detect_liquidity_sweeps(
            bars,
            supplied_analysis((high,), (unsupported_break,)),
        )


def test_ambiguous_event_cannot_reuse_a_previously_consumed_level() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=10)
    bars[3] = candle(3, open_=13, high=14, low=12, close=13)
    bars[5] = candle(5, open_=10, high=13, low=9, close=11)
    bars[6] = candle(6, open_=11, high=13, low=9, close=11)
    high = swing(bars, SwingKind.HIGH, 2, 10, 4)
    low = swing(bars, SwingKind.LOW, 3, 12, 5)
    first_break = StructureEvent(
        kind=EventKind.BOS,
        direction=Direction.BULLISH,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=10,
        level_index=2,
    )
    ambiguous = StructureEvent(
        kind=EventKind.AMBIGUOUS_BREAK,
        direction=None,
        index=6,
        timestamp=bars[6].timestamp,
        level_price=None,
        level_index=None,
    )

    with pytest.raises(ValueError, match="eligible active swings"):
        detect_liquidity_sweeps(
            bars,
            supplied_analysis((high, low), (first_break, ambiguous)),
        )


def test_analyzer_consumes_first_inverted_level_before_opposing_break() -> None:
    prices = [
        (7, 8, 6, 7),
        (7, 9, 6, 8),
        (8, 10, 7, 8),
        (7, 9, 6, 7),
        (7, 8, 6, 7),
        (14, 15, 13.5, 14),
        (14, 15, 13, 14),
        (13, 14, 12, 13),
        (14, 15, 13, 14),
        (14, 15, 13.5, 14),
        (11, 14, 10, 11),
    ]
    bars = [
        Candle(
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)
            + timedelta(minutes=index),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=100,
        )
        for index, (open_, high, low, close) in enumerate(prices)
    ]

    analysis = analyze_market_structure(bars)
    sweeps = detect_liquidity_sweeps(bars, analysis)

    assert any(
        event.kind is EventKind.BOS
        and event.index == 5
        and event.level_index == 2
        for event in analysis.events
    )
    assert any(
        swing.kind is SwingKind.LOW
        and swing.index == 7
        and swing.price == 12
        and swing.confirmed_at_index == 9
        for swing in analysis.swings
    )
    assert bars[10].close > 10 and bars[10].close < 12
    assert any(
        event.kind is EventKind.CHOCH
        and event.index == 10
        and event.direction is Direction.BEARISH
        and event.level_index == 7
        for event in analysis.events
    )
    assert all(
        event.kind is not EventKind.AMBIGUOUS_BREAK
        for event in analysis.events
        if event.index == 10
    )
    assert all(event.index != 10 for event in sweeps)


def test_inconsistent_ambiguous_event_is_rejected() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15, low=5)
    bars[5] = candle(5, open_=11, high=16, low=3, close=10)
    high = swing(bars, SwingKind.HIGH, 2, 15, 4)
    low = swing(bars, SwingKind.LOW, 2, 5, 4)
    inconsistent = StructureEvent(
        kind=EventKind.AMBIGUOUS_BREAK,
        direction=None,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=None,
        level_index=None,
    )

    with pytest.raises(ValueError, match="opposing close breaks"):
        detect_liquidity_sweeps(
            bars,
            supplied_analysis((high, low), (inconsistent,)),
        )


@pytest.mark.parametrize(
    ("level_index", "level_price", "message"),
    [
        (3, 15, "unknown swing identity"),
        (2, 14, "level price does not match"),
    ],
)
def test_inconsistent_structural_event_is_rejected_before_consumption(
    level_index: int, level_price: float, message: str
) -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15)
    bars[3] = candle(3, open_=13, high=14, low=12, close=13)
    bars[5] = candle(5, open_=14, high=17, low=13, close=16)
    bars[6] = candle(6, open_=14, high=16, low=13, close=14)
    high = swing(bars, SwingKind.HIGH, 2, 15, 4)
    low = swing(bars, SwingKind.LOW, 3, 12, 5)
    inconsistent = StructureEvent(
        kind=EventKind.BOS,
        direction=Direction.BULLISH,
        index=5,
        timestamp=bars[5].timestamp,
        level_price=level_price,
        level_index=level_index,
    )

    with pytest.raises(ValueError, match=message):
        detect_liquidity_sweeps(
            bars,
            supplied_analysis((high, low), (inconsistent,)),
        )


def test_valid_break_reference_leaves_unrelated_active_swing_eligible() -> None:
    bars = [candle(i) for i in range(9)]
    bars[2] = replace(bars[2], high=15)
    bars[3] = candle(3, open_=13, high=14, low=12, close=13)
    bars[6] = candle(6, open_=14, high=16, low=10, close=11)
    high = swing(bars, SwingKind.HIGH, 2, 15, 4)
    low = swing(bars, SwingKind.LOW, 3, 12, 5)
    valid_break = StructureEvent(
        kind=EventKind.CHOCH,
        direction=Direction.BEARISH,
        index=6,
        timestamp=bars[6].timestamp,
        level_price=12,
        level_index=3,
    )

    events = detect_liquidity_sweeps(
        bars,
        supplied_analysis((high, low), (valid_break,)),
    )

    assert [(event.swing_kind, event.swing_index) for event in events] == [
        (SwingKind.HIGH, 2)
    ]


def test_detector_rejects_insufficient_and_invalid_candle_inputs() -> None:
    short_bars = [candle(i) for i in range(4)]
    with pytest.raises(ValueError, match="at least five candles"):
        detect_liquidity_sweeps(short_bars, supplied_analysis(()))

    bars = [candle(i) for i in range(6)]
    bars[3] = replace(bars[3], high=7)
    with pytest.raises(ValueError, match="high is below open or close"):
        detect_liquidity_sweeps(bars, supplied_analysis(()))


def test_detector_rejects_inconsistent_swing_metadata() -> None:
    bars = [candle(i) for i in range(7)]
    bars[2] = replace(bars[2], high=15)
    invalid = swing(bars, SwingKind.HIGH, 2, 14, 4)

    with pytest.raises(ValueError, match="match its pivot candle"):
        detect_liquidity_sweeps(bars, supplied_analysis((invalid,)))


def test_detector_output_is_deterministic() -> None:
    bars = [candle(i) for i in range(9)]
    analysis = high_swing_analysis(bars)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=14)
    analysis = analyze_market_structure(bars)

    assert detect_liquidity_sweeps(bars, analysis) == detect_liquidity_sweeps(
        bars, analysis
    )


def test_future_suffix_changes_do_not_change_historical_sweeps() -> None:
    prefix_size = 9
    prefix = [candle(i) for i in range(prefix_size)]
    prefix[2] = replace(prefix[2], high=15)
    prefix[5] = candle(5, open_=14, high=16, low=13, close=14)
    calm_suffix = [candle(i) for i in range(prefix_size, 15)]
    volatile_suffix = [
        candle(9, open_=30, high=40, low=25, close=35),
        candle(10, open_=8, high=12, low=2, close=4),
        candle(11, open_=50, high=60, low=45, close=55),
        candle(12, open_=3, high=7, low=1, close=2),
        candle(13, open_=20, high=25, low=15, close=18),
        candle(14, open_=6, high=10, low=4, close=8),
    ]
    first_bars = [*prefix, *calm_suffix]
    second_bars = [*prefix, *volatile_suffix]

    first = detect_liquidity_sweeps(
        first_bars, analyze_market_structure(first_bars)
    )
    second = detect_liquidity_sweeps(
        second_bars, analyze_market_structure(second_bars)
    )

    assert tuple(event for event in first if event.index < prefix_size) == tuple(
        event for event in second if event.index < prefix_size
    )
