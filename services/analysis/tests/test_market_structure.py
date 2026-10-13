from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tradiopro_analysis.market_structure import (
    Candle,
    Direction,
    EventKind,
    StructureLabel,
    Swing,
    SwingKind,
    TrendState,
    _process_active_levels,
    analyze_market_structure,
)


def candle(
    index: int,
    *,
    open_: float = 10,
    high: float = 11,
    low: float = 9,
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


def with_changes(
    bars: list[Candle], index: int, **changes: float
) -> list[Candle]:
    result = bars.copy()
    result[index] = replace(result[index], **changes)
    return result


def swing_fixture(
    *,
    high_pivots: dict[int, float] | None = None,
    low_pivots: dict[int, float] | None = None,
    size: int = 9,
) -> list[Candle]:
    high_pivots = high_pivots or {}
    low_pivots = low_pivots or {}
    bars = [candle(i, high=12, low=8) for i in range(size)]
    for index, price in high_pivots.items():
        bars[index] = replace(bars[index], high=price)
    for index, price in low_pivots.items():
        bars[index] = replace(bars[index], low=price)
    return bars


def structural_swing(kind: SwingKind, index: int, price: float) -> Swing:
    return Swing(
        kind=kind,
        index=index,
        timestamp=candle(index).timestamp,
        price=price,
        label=None,
        confirmed_at_index=index + 2,
        confirmed_at=candle(index + 2).timestamp,
    )


def test_valid_candles_are_accepted() -> None:
    result = analyze_market_structure([candle(i) for i in range(5)])

    assert result.swings == ()
    assert result.events == ()
    assert result.trend is TrendState.UNINITIALIZED


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"open": 0}, "prices must be positive"),
        ({"high": float("inf")}, "must be finite"),
        ({"volume": float("nan")}, "must be finite"),
        ({"volume": -1}, "cannot be negative"),
        ({"low": 10.5}, "low exceeds open or close"),
        ({"high": 9.5}, "high is below open or close"),
    ],
)
def test_invalid_candle_values_are_rejected(
    changes: dict[str, float], message: str
) -> None:
    bars = [candle(i) for i in range(5)]
    bars[2] = replace(bars[2], **changes)

    with pytest.raises(ValueError, match=message):
        analyze_market_structure(bars)


def test_naive_and_out_of_order_timestamps_are_rejected() -> None:
    bars = [candle(i) for i in range(5)]
    bars[2] = replace(bars[2], timestamp=datetime(2025, 1, 1))
    with pytest.raises(ValueError, match="timezone"):
        analyze_market_structure(bars)

    bars = [candle(i) for i in range(5)]
    bars[3] = replace(bars[3], timestamp=bars[2].timestamp)
    with pytest.raises(ValueError, match="strictly increasing"):
        analyze_market_structure(bars)


def test_non_datetime_timestamp_is_rejected() -> None:
    bars = [candle(i) for i in range(5)]
    bars[2] = replace(bars[2], timestamp="2025-01-01")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="must be a datetime"):
        analyze_market_structure(bars)


def test_strict_swing_high_and_low_confirmation() -> None:
    bars = swing_fixture(high_pivots={2: 15}, low_pivots={5: 5}, size=9)

    swings = analyze_market_structure(bars).swings

    high = next(s for s in swings if s.kind is SwingKind.HIGH)
    low = next(s for s in swings if s.kind is SwingKind.LOW)
    assert (high.index, high.price, high.label) == (2, 15, None)
    assert (high.confirmed_at_index, high.confirmed_at) == (
        4,
        bars[4].timestamp,
    )
    assert (low.index, low.price, low.label) == (5, 5, None)
    assert low.confirmed_at_index == 7


def test_equal_neighbor_high_or_low_is_not_a_pivot() -> None:
    bars = swing_fixture(high_pivots={2: 15}, low_pivots={5: 5}, size=9)
    bars[1] = replace(bars[1], high=15)
    bars[6] = replace(bars[6], low=5)

    assert analyze_market_structure(bars).swings == ()


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        ([15, 16], [None, StructureLabel.HH]),
        ([16, 15], [None, StructureLabel.LH]),
        ([5, 6], [None, StructureLabel.HL]),
        ([6, 5], [None, StructureLabel.LL]),
        ([15, 15], [None, StructureLabel.EQH]),
        ([5, 5], [None, StructureLabel.EQL]),
    ],
)
def test_swing_classification_against_previous_same_type(
    prices: list[float], expected: list[StructureLabel | None]
) -> None:
    kind = SwingKind.HIGH if expected[-1] in {
        StructureLabel.HH,
        StructureLabel.LH,
        StructureLabel.EQH,
    } else SwingKind.LOW
    key = "high_pivots" if kind is SwingKind.HIGH else "low_pivots"
    bars = swing_fixture(
        **{key: {2: prices[0], 6: prices[1]}},
        size=9,
    )

    swings = [s for s in analyze_market_structure(bars).swings if s.kind is kind]

    assert [s.label for s in swings] == expected


def test_bullish_bos_from_uninitialized_trend() -> None:
    bars = swing_fixture(high_pivots={2: 15}, size=9)
    bars[5] = replace(bars[5], open=14, high=17, low=13, close=16)

    result = analyze_market_structure(bars)
    breaks = [event for event in result.events if event.kind is EventKind.BOS]

    assert len(breaks) == 1
    assert breaks[0].direction is Direction.BULLISH
    assert breaks[0].index == 5
    assert result.trend is TrendState.BULLISH


def test_bearish_bos_from_uninitialized_trend() -> None:
    bars = swing_fixture(low_pivots={2: 5}, size=9)
    bars[5] = replace(bars[5], open=6, high=7, low=3, close=4)

    result = analyze_market_structure(bars)
    breaks = [event for event in result.events if event.kind is EventKind.BOS]

    assert len(breaks) == 1
    assert breaks[0].direction is Direction.BEARISH
    assert result.trend is TrendState.BEARISH


def test_bullish_continuation_break_is_bos() -> None:
    bars = swing_fixture(high_pivots={2: 15, 8: 17}, size=13)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=16)
    bars[11] = replace(bars[11], open=18, high=19, low=17, close=18)

    result = analyze_market_structure(bars)
    breaks = [event for event in result.events if event.kind is EventKind.BOS]

    assert [(event.index, event.direction) for event in breaks] == [
        (5, Direction.BULLISH),
        (11, Direction.BULLISH),
    ]
    assert result.trend is TrendState.BULLISH


def test_bearish_continuation_break_is_bos() -> None:
    bars = swing_fixture(low_pivots={2: 5}, size=13)
    bars[5] = replace(bars[5], open=6, high=7, low=3, close=4)
    bars[6] = replace(bars[6], open=7, high=8, low=2, close=7)
    bars[11] = replace(bars[11], open=3, high=4, low=1, close=1.5)

    result = analyze_market_structure(bars)
    breaks = [event for event in result.events if event.kind is EventKind.BOS]

    assert [(event.index, event.direction) for event in breaks] == [
        (5, Direction.BEARISH),
        (11, Direction.BEARISH),
    ]
    assert result.trend is TrendState.BEARISH


@pytest.mark.parametrize(
    ("initial", "opposite", "expected"),
    [
        (Direction.BULLISH, Direction.BEARISH, Direction.BEARISH),
        (Direction.BEARISH, Direction.BULLISH, Direction.BULLISH),
    ],
)
def test_choch_reverses_an_initialized_trend(
    initial: Direction, opposite: Direction, expected: Direction
) -> None:
    if initial is Direction.BULLISH:
        bars = swing_fixture(
            high_pivots={2: 15},
            low_pivots={2: 5},
            size=11,
        )
        bars[5] = replace(bars[5], open=14, high=17, low=13, close=16)
        bars[6] = replace(bars[6], open=6, high=7, low=3, close=4)
    else:
        bars = swing_fixture(
            high_pivots={2: 15},
            low_pivots={2: 5},
            size=11,
        )
        bars[5] = replace(bars[5], open=6, high=7, low=3, close=4)
        bars[6] = replace(bars[6], open=14, high=17, low=13, close=16)

    result = analyze_market_structure(bars)
    changes = [event for event in result.events if event.kind is EventKind.CHOCH]

    assert len(changes) == 1
    assert changes[0].direction is opposite
    assert result.trend.value == expected.value


def test_wick_penetration_without_close_is_not_a_break() -> None:
    bars = swing_fixture(high_pivots={2: 15}, size=9)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=14)

    result = analyze_market_structure(bars)

    assert [event.kind for event in result.events] == [
        EventKind.WICK_PENETRATION
    ]
    assert result.events[0].direction is Direction.BULLISH
    assert result.trend is TrendState.UNINITIALIZED


def test_repeated_level_and_break_attempt_produce_one_close_break() -> None:
    bars = swing_fixture(high_pivots={2: 15, 6: 15}, size=11)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=16)
    bars[6] = replace(bars[6], open=14, high=16, low=13, close=16)
    for index in (7, 8):
        bars[index] = replace(bars[index], high=16)

    result = analyze_market_structure(bars)
    breaks = [
        event
        for event in result.events
        if event.kind in {EventKind.BOS, EventKind.CHOCH}
    ]

    assert [s.label for s in result.swings if s.kind is SwingKind.HIGH] == [None]
    assert len(breaks) == 1
    assert breaks[0].index == 5


def test_later_equal_price_swing_has_independent_break_identity() -> None:
    bars = swing_fixture(high_pivots={2: 15, 9: 15}, size=14)
    bars[5] = replace(bars[5], open=14, high=17, low=13, close=16)
    bars[6] = replace(bars[6], high=17)
    bars[12] = replace(bars[12], open=14, high=17, low=13, close=16)

    result = analyze_market_structure(bars)
    breaks = [
        event
        for event in result.events
        if event.kind in {EventKind.BOS, EventKind.CHOCH}
    ]

    assert [
        (event.index, event.level_index, event.level_price) for event in breaks
    ] == [(5, 2, 15), (12, 9, 15)]
    equal_price_swings = [
        swing
        for swing in result.swings
        if swing.kind is SwingKind.HIGH and swing.index == 9
    ]
    assert len(equal_price_swings) == 1
    assert equal_price_swings[0].price == 15
    assert equal_price_swings[0].label is StructureLabel.EQH
    assert equal_price_swings[0].confirmed_at_index == 11


def test_wick_only_penetration_does_not_consume_swing() -> None:
    active_high = structural_swing(SwingKind.HIGH, 2, 10)
    broken_levels: set[tuple[SwingKind, int]] = set()
    wick_events, trend = _process_active_levels(
        5,
        candle(5, open_=9, high=11, low=8, close=9),
        active_high,
        None,
        broken_levels,
        TrendState.UNINITIALIZED,
    )
    assert (SwingKind.HIGH, active_high.index) not in broken_levels
    close_events, trend = _process_active_levels(
        6,
        candle(6, open_=9, high=11, low=8, close=10.5),
        active_high,
        None,
        broken_levels,
        trend,
    )

    assert [event.kind for event in wick_events] == [EventKind.WICK_PENETRATION]
    assert [event.kind for event in close_events] == [
        EventKind.WICK_PENETRATION,
        EventKind.BOS,
    ]
    assert trend is TrendState.BULLISH


def test_ambiguous_close_preserves_both_wicks_and_consumes_broken_swings() -> None:
    active_high = structural_swing(SwingKind.HIGH, 2, 10)
    active_low = structural_swing(SwingKind.LOW, 3, 12)
    broken_levels: set[tuple[SwingKind, int]] = set()

    events, trend = _process_active_levels(
        8,
        candle(8, open_=11, high=13, low=9, close=11),
        active_high,
        active_low,
        broken_levels,
        TrendState.UNINITIALIZED,
    )

    assert [(event.kind, event.direction) for event in events] == [
        (EventKind.WICK_PENETRATION, Direction.BULLISH),
        (EventKind.WICK_PENETRATION, Direction.BEARISH),
        (EventKind.AMBIGUOUS_BREAK, None),
    ]
    assert broken_levels == {
        (SwingKind.HIGH, active_high.index),
        (SwingKind.LOW, active_low.index),
    }
    assert trend is TrendState.AMBIGUOUS


@pytest.mark.parametrize(
    ("kind", "direction", "bar"),
    [
        (
            SwingKind.HIGH,
            Direction.BULLISH,
            candle(9, open_=11, high=13, low=10.5, close=11.5),
        ),
        (
            SwingKind.LOW,
            Direction.BEARISH,
            candle(9, open_=11, high=11.5, low=9, close=10.5),
        ),
    ],
)
def test_directional_break_after_ambiguity_stays_unresolved(
    kind: SwingKind, direction: Direction, bar: Candle
) -> None:
    active_high = structural_swing(SwingKind.HIGH, 2, 10)
    active_low = structural_swing(SwingKind.LOW, 3, 12)
    broken_levels: set[tuple[SwingKind, int]] = set()
    _, trend = _process_active_levels(
        8,
        candle(8, open_=11, high=13, low=9, close=11),
        active_high,
        active_low,
        broken_levels,
        TrendState.UNINITIALIZED,
    )

    new_level = structural_swing(kind, 6, 10 if kind is SwingKind.HIGH else 12)
    events, trend = _process_active_levels(
        9,
        bar,
        new_level if kind is SwingKind.HIGH else None,
        new_level if kind is SwingKind.LOW else None,
        broken_levels,
        trend,
    )
    repeated_events, repeated_trend = _process_active_levels(
        10,
        bar,
        new_level if kind is SwingKind.HIGH else None,
        new_level if kind is SwingKind.LOW else None,
        broken_levels,
        trend,
    )

    assert any(
        event.kind is EventKind.UNRESOLVED_BREAK
        and event.direction is direction
        for event in events
    )
    assert all(
        event.kind not in {EventKind.BOS, EventKind.CHOCH}
        for event in (*events, *repeated_events)
    )
    assert not any(
        event.kind is EventKind.UNRESOLVED_BREAK for event in repeated_events
    )
    assert trend is repeated_trend is TrendState.AMBIGUOUS


def test_repeated_wicks_are_recorded_but_not_promoted_to_breaks() -> None:
    bars = swing_fixture(high_pivots={2: 15}, size=9)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=14)
    bars[6] = replace(bars[6], open=14, high=17, low=13, close=14)

    result = analyze_market_structure(bars)

    assert [event.kind for event in result.events] == [
        EventKind.WICK_PENETRATION,
        EventKind.WICK_PENETRATION,
    ]
    assert result.trend is TrendState.UNINITIALIZED


def test_close_break_records_wick_and_close_events_separately() -> None:
    bars = swing_fixture(high_pivots={2: 15}, size=9)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=16)

    result = analyze_market_structure(bars)

    assert [event.kind for event in result.events] == [
        EventKind.WICK_PENETRATION,
        EventKind.BOS,
    ]


def test_insufficient_history_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least five candles"):
        analyze_market_structure([candle(i) for i in range(4)])


def test_uninitialized_trend_does_not_produce_choch() -> None:
    bars = swing_fixture(high_pivots={2: 15}, size=9)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=15)

    result = analyze_market_structure(bars)

    assert all(event.kind is not EventKind.CHOCH for event in result.events)
    assert result.trend is TrendState.UNINITIALIZED


def test_confirmation_close_cannot_break_newly_confirmed_pivot() -> None:
    bars = swing_fixture(high_pivots={2: 15}, size=9)
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=16)

    result = analyze_market_structure(bars)

    assert any(s.kind is SwingKind.HIGH and s.confirmed_at_index == 4 for s in result.swings)
    assert all(
        not (
            event.index < 5
            and event.kind in {EventKind.BOS, EventKind.CHOCH}
            and event.level_index == 2
        )
        for event in result.events
    )
    assert any(
        event.index == 5
        and event.kind is EventKind.BOS
        and event.level_index == 2
        for event in result.events
    )


def test_historical_prefix_matches_full_run_through_prefix_close() -> None:
    bars = swing_fixture(
        high_pivots={2: 15, 6: 17},
        low_pivots={4: 5},
        size=11,
    )
    bars[5] = replace(bars[5], open=14, high=16, low=13, close=16)

    prefix = analyze_market_structure(bars[:8])
    full = analyze_market_structure(bars)
    prefix_events = tuple(event for event in full.events if event.index < 8)
    prefix_swings = tuple(
        swing for swing in full.swings if swing.confirmed_at_index < 8
    )

    assert prefix.events == prefix_events
    assert prefix.swings == prefix_swings
    assert prefix.trend is full.trend


def test_inverted_levels_in_full_analysis_do_not_reuse_consumed_swing() -> None:
    bars = [
        candle(i, open_=8.5, high=9, low=8, close=8.5)
        for i in range(12)
    ]
    bars[2] = replace(bars[2], high=10)
    for index in (5, 6, 7, 8, 9):
        bars[index] = candle(index, open_=13.5, high=14, low=13, close=13.5)
    bars[7] = replace(bars[7], low=12)
    bars[10] = candle(10, open_=13, high=14, low=10, close=11)
    bars[11] = candle(11, open_=11, high=12, low=10, close=11)

    result = analyze_market_structure(bars)
    close_breaks = [
        event
        for event in result.events
        if event.kind in {EventKind.BOS, EventKind.CHOCH}
    ]

    assert [(event.index, event.kind, event.direction) for event in close_breaks] == [
        (5, EventKind.BOS, Direction.BULLISH),
        (10, EventKind.CHOCH, Direction.BEARISH),
    ]
    assert any(
        swing.kind is SwingKind.LOW
        and swing.index == 7
        and swing.confirmed_at_index == 9
        for swing in result.swings
    )
    assert all(event.kind is not EventKind.AMBIGUOUS_BREAK for event in result.events)
    assert result.trend is TrendState.BEARISH


def test_future_suffix_perturbation_preserves_historical_outputs() -> None:
    prefix_size = 9
    prefix = swing_fixture(
        high_pivots={2: 15, 6: 17},
        low_pivots={4: 5},
        size=prefix_size,
    )
    calm_suffix = [candle(i) for i in range(prefix_size, 15)]
    volatile_suffix = [
        candle(9, open_=30, high=40, low=25, close=35, volume=1000),
        candle(10, open_=8, high=12, low=2, close=4, volume=2000),
        candle(11, open_=50, high=60, low=45, close=55, volume=3000),
        candle(12, open_=3, high=7, low=1, close=2, volume=4000),
        candle(13, open_=20, high=25, low=15, close=18, volume=5000),
        candle(14, open_=6, high=10, low=4, close=8, volume=6000),
    ]

    first = analyze_market_structure([*prefix, *calm_suffix])
    second = analyze_market_structure([*prefix, *volatile_suffix])

    # Only events occurring and swings confirmed within the prefix are
    # compared; final trend and swings confirmed in the suffix may change.
    first_events = tuple(event for event in first.events if event.index < prefix_size)
    second_events = tuple(event for event in second.events if event.index < prefix_size)
    first_swings = tuple(
        swing for swing in first.swings if swing.confirmed_at_index < prefix_size
    )
    second_swings = tuple(
        swing for swing in second.swings if swing.confirmed_at_index < prefix_size
    )

    assert first_events == second_events
    assert first_swings == second_swings
