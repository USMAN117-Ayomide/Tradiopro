from datetime import datetime, timedelta, timezone

from tradiopro_analysis.liquidity_sweeps import (
    LiquiditySweepKind,
    detect_liquidity_sweeps,
)
from tradiopro_analysis.market_structure import (
    Candle,
    Direction,
    EventKind,
    StructureLabel,
    SwingKind,
    TrendState,
    analyze_market_structure,
)


def candles_from_ohlc(
    rows: tuple[tuple[float, float, float, float], ...],
) -> list[Candle]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(start + timedelta(minutes=index), *ohlc, 100)
        for index, ohlc in enumerate(rows)
    ]


def test_reference_strict_swing_high_and_low_confirmation() -> None:
    candles = [
        Candle(datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc), 10, 12, 8, 10, 100),
        Candle(datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc), 11, 13, 7, 12, 100),
        Candle(datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc), 14, 16, 9, 15, 100),
        Candle(datetime(2025, 1, 1, 0, 3, tzinfo=timezone.utc), 10, 14, 6, 8, 100),
        Candle(datetime(2025, 1, 1, 0, 4, tzinfo=timezone.utc), 9, 13, 7, 10, 100),
        Candle(datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc), 8, 12, 5, 6, 100),
        Candle(datetime(2025, 1, 1, 0, 6, tzinfo=timezone.utc), 7, 11, 4, 5, 100),
        Candle(datetime(2025, 1, 1, 0, 7, tzinfo=timezone.utc), 6, 12, 6, 10, 100),
        Candle(datetime(2025, 1, 1, 0, 8, tzinfo=timezone.utc), 10, 13, 7, 12, 100),
    ]

    # Index 2 exceeds both neighboring highs on each side and is confirmed at 4.
    # Index 6 is below both neighboring lows on each side and is confirmed at 8.
    result = analyze_market_structure(candles)

    highs = [swing for swing in result.swings if swing.kind is SwingKind.HIGH]
    lows = [swing for swing in result.swings if swing.kind is SwingKind.LOW]

    assert [
        (swing.index, swing.price, swing.confirmed_at_index) for swing in highs
    ] == [(2, 16, 4)]
    assert [
        (swing.index, swing.price, swing.confirmed_at_index) for swing in lows
    ] == [(6, 4, 8)]


def test_reference_higher_and_lower_swing_classifications() -> None:
    candles = [
        Candle(datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc), 10, 12, 8, 10, 100),
        Candle(datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc), 10, 13, 7, 11, 100),
        Candle(datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc), 14, 16, 6, 15, 100),
        Candle(datetime(2025, 1, 1, 0, 3, tzinfo=timezone.utc), 10, 14, 5, 8, 100),
        Candle(datetime(2025, 1, 1, 0, 4, tzinfo=timezone.utc), 9, 13, 7, 10, 100),
        Candle(datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc), 10, 15, 6, 11, 100),
        Candle(datetime(2025, 1, 1, 0, 6, tzinfo=timezone.utc), 16, 18, 5, 17, 100),
        Candle(datetime(2025, 1, 1, 0, 7, tzinfo=timezone.utc), 10, 16, 3, 7, 100),
        Candle(datetime(2025, 1, 1, 0, 8, tzinfo=timezone.utc), 9, 14, 6, 10, 100),
        Candle(datetime(2025, 1, 1, 0, 9, tzinfo=timezone.utc), 10, 15, 5, 11, 100),
        Candle(datetime(2025, 1, 1, 0, 10, tzinfo=timezone.utc), 15, 17, 6, 16, 100),
        Candle(datetime(2025, 1, 1, 0, 11, tzinfo=timezone.utc), 8, 16, 4, 10, 100),
        Candle(datetime(2025, 1, 1, 0, 12, tzinfo=timezone.utc), 10, 15, 5, 12, 100),
        Candle(datetime(2025, 1, 1, 0, 13, tzinfo=timezone.utc), 11, 16, 6, 13, 100),
    ]

    # High pivots at 2, 6, and 10 confirm at 4, 8, and 12: 16 is the
    # unlabelled first high, 18 > 16 is HH, and 17 < 18 is LH.
    # Low pivots at 3, 7, and 11 confirm at 5, 9, and 13: 5 is the
    # unlabelled first low, 3 < 5 is LL, and 4 > 3 is HL.
    result = analyze_market_structure(candles)

    highs = [swing for swing in result.swings if swing.kind is SwingKind.HIGH]
    lows = [swing for swing in result.swings if swing.kind is SwingKind.LOW]

    assert [
        (swing.index, swing.price, swing.confirmed_at_index, swing.label)
        for swing in highs
    ] == [
        (2, 16, 4, None),
        (6, 18, 8, StructureLabel.HH),
        (10, 17, 12, StructureLabel.LH),
    ]
    assert [
        (swing.index, swing.price, swing.confirmed_at_index, swing.label)
        for swing in lows
    ] == [
        (3, 5, 5, None),
        (7, 3, 9, StructureLabel.LL),
        (11, 4, 13, StructureLabel.HL),
    ]


def test_reference_bullish_close_confirmed_bos() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 17, 13, 16),
        )
    )

    # The high at index 2 (15) is strictly above highs at 0, 1, 3, and 4,
    # so it confirms at 4. Candle 5 closes above it: bullish BOS, level 2,
    # with bullish trend.
    result = analyze_market_structure(candles)

    close_breaks = [
        event for event in result.events if event.kind is EventKind.BOS
    ]
    assert [
        (event.direction, event.index, event.level_index, event.level_price)
        for event in close_breaks
    ] == [(Direction.BULLISH, 5, 2, 15)]
    assert result.trend is TrendState.BULLISH


def test_reference_bearish_close_confirmed_bos() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (8, 13, 7, 8),
            (6, 11, 5, 6),
            (7, 12, 6, 7),
            (8, 10, 7, 8),
            (6, 9, 3, 4),
        )
    )

    # The low at index 2 (5) is strictly below lows at 0, 1, 3, and 4,
    # so it confirms at 4. Candle 5 closes below it: bearish BOS, level 2,
    # with bearish trend.
    result = analyze_market_structure(candles)

    close_breaks = [
        event for event in result.events if event.kind is EventKind.BOS
    ]
    assert [
        (event.direction, event.index, event.level_index, event.level_price)
        for event in close_breaks
    ] == [(Direction.BEARISH, 5, 2, 5)]
    assert result.trend is TrendState.BEARISH


def test_reference_choch_against_established_bullish_trend() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 17, 13, 16),
            (8, 12, 5, 7),
            (7, 11, 6, 8),
            (8, 10, 7, 9),
            (6, 9, 3, 4),
        )
    )

    # The high at 2 confirms at 4; candle 5 closes above 15 and establishes
    # bullish trend with BOS. The low at 6 (5) is below lows at 4, 5, 7, 8
    # and confirms at 8. Candle 9 closes below 5: bearish CHoCH, level 6,
    # leaving bearish trend.
    result = analyze_market_structure(candles)

    close_breaks = [
        event
        for event in result.events
        if event.kind in {EventKind.BOS, EventKind.CHOCH}
    ]
    assert [
        (event.kind, event.direction, event.index, event.level_index, event.level_price)
        for event in close_breaks
    ] == [
        (EventKind.BOS, Direction.BULLISH, 5, 2, 15),
        (EventKind.CHOCH, Direction.BEARISH, 9, 6, 5),
    ]
    assert result.trend is TrendState.BEARISH


def test_reference_choch_against_established_bearish_trend() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (8, 13, 7, 8),
            (6, 11, 5, 6),
            (7, 12, 6, 7),
            (8, 10, 7, 8),
            (6, 9, 3, 4),
            (10, 18, 7, 11),
            (12, 16, 6, 14),
            (13, 14, 8, 12),
            (17, 20, 16, 19),
        )
    )

    # The low at 2 confirms at 4; candle 5 closes below 5 and establishes
    # bearish trend with BOS. The high at 6 (18) is above highs at 4, 5, 7,
    # 8 and confirms at 8. Candle 9 closes above 18: bullish CHoCH, level 6,
    # leaving bullish trend.
    result = analyze_market_structure(candles)

    close_breaks = [
        event
        for event in result.events
        if event.kind in {EventKind.BOS, EventKind.CHOCH}
    ]
    assert [
        (event.kind, event.direction, event.index, event.level_index, event.level_price)
        for event in close_breaks
    ] == [
        (EventKind.BOS, Direction.BEARISH, 5, 2, 5),
        (EventKind.CHOCH, Direction.BULLISH, 9, 6, 18),
    ]
    assert result.trend is TrendState.BULLISH


def test_reference_wick_only_penetration_is_not_a_close_break() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 16, 13, 14),
        )
    )

    # The high at 2 (15) confirms at 4. Candle 5 wicks to 16 but closes at
    # 14, below the level: wick penetration only, no BOS, trend uninitialized.
    result = analyze_market_structure(candles)

    assert [
        (event.kind, event.direction, event.index, event.level_index, event.level_price)
        for event in result.events
    ] == [(EventKind.WICK_PENETRATION, Direction.BULLISH, 5, 2, 15)]
    assert result.trend is TrendState.UNINITIALIZED


def test_reference_high_side_liquidity_sweep() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 16, 13, 14),
        )
    )

    # High 15 at index 2 exceeds highs at 0, 1, 3, 4 and confirms at 4.
    # It is eligible from index 5. That candle reaches 16 and closes at 14,
    # strictly below the level: one bearish sweep of the high at index 2.
    analysis = analyze_market_structure(candles)
    events = detect_liquidity_sweeps(candles, analysis)

    assert [
        (
            event.kind,
            event.direction,
            event.index,
            event.swing_kind,
            event.swing_index,
            event.swing_price,
            event.penetration_price,
            event.rejection_close,
        )
        for event in events
    ] == [
        (
            LiquiditySweepKind.LIQUIDITY_SWEEP,
            Direction.BEARISH,
            5,
            SwingKind.HIGH,
            2,
            15,
            16,
            14,
        )
    ]


def test_reference_low_side_liquidity_sweep() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (12, 13, 7, 12),
            (6, 11, 5, 6),
            (7, 12, 6, 7),
            (8, 10, 7, 8),
            (6, 7, 3, 6),
        )
    )

    # Low 5 at index 2 is below lows at 0, 1, 3, 4 and confirms at 4.
    # It is eligible from index 5. That candle reaches 3 and closes at 6,
    # strictly above the level: one bullish sweep of the low at index 2.
    analysis = analyze_market_structure(candles)
    events = detect_liquidity_sweeps(candles, analysis)

    assert [
        (
            event.kind,
            event.direction,
            event.index,
            event.swing_kind,
            event.swing_index,
            event.swing_price,
            event.penetration_price,
            event.rejection_close,
        )
        for event in events
    ] == [
        (
            LiquiditySweepKind.LIQUIDITY_SWEEP,
            Direction.BULLISH,
            5,
            SwingKind.LOW,
            2,
            5,
            3,
            6,
        )
    ]


def test_reference_wick_penetrations_without_rejection_are_not_sweeps() -> None:
    high_candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 16, 13, 15),
        )
    )
    low_candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (12, 13, 7, 12),
            (6, 11, 5, 6),
            (7, 12, 6, 7),
            (8, 10, 7, 8),
            (6, 7, 3, 5),
        )
    )

    # High pivot 2 (15) confirms at 4; at 5, high 16 penetrates but close
    # equals 15, so there is no strict rejection. Low pivot 2 (5) also
    # confirms at 4; at 5, low 3 penetrates but close equals 5.
    # Neither exact close-at-level case is a sweep.
    high_events = detect_liquidity_sweeps(
        high_candles, analyze_market_structure(high_candles)
    )
    low_events = detect_liquidity_sweeps(
        low_candles, analyze_market_structure(low_candles)
    )

    assert high_events == ()
    assert low_events == ()


def test_reference_high_side_penetration_closing_above_is_not_a_sweep() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 16, 13, 16),
        )
    )

    # The high 15 at index 2 exceeds highs 12, 13, 14, 13 at indices 0, 1,
    # 3, 4, and confirms at 4. Candle 5 is eligible, penetrates to 16, and
    # closes at 16 above the level, so it cannot be a rejected high sweep.
    analysis = analyze_market_structure(candles)
    highs = [swing for swing in analysis.swings if swing.kind is SwingKind.HIGH]
    assert [
        (swing.index, swing.price, swing.confirmed_at_index) for swing in highs
    ] == [(2, 15, 4)]

    candidate = candles[5]
    assert candidate.high > 15
    assert candidate.close > 15
    events = detect_liquidity_sweeps(candles, analysis)

    assert not any(
        event.swing_kind is SwingKind.HIGH and event.swing_index == 2
        for event in events
    )


def test_reference_low_side_penetration_closing_below_is_not_a_sweep() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (12, 13, 7, 12),
            (6, 11, 5, 6),
            (7, 12, 6, 7),
            (8, 10, 7, 8),
            (6, 7, 3, 4),
        )
    )

    # The low 5 at index 2 is below lows 8, 7, 6, 7 at indices 0, 1, 3, 4,
    # and confirms at 4. Candle 5 is eligible, penetrates to 3, and closes
    # at 4 below the level, so it cannot be a rejected low sweep.
    analysis = analyze_market_structure(candles)
    lows = [swing for swing in analysis.swings if swing.kind is SwingKind.LOW]
    assert [
        (swing.index, swing.price, swing.confirmed_at_index) for swing in lows
    ] == [(2, 5, 4)]

    candidate = candles[5]
    assert candidate.low < 5
    assert candidate.close < 5
    events = detect_liquidity_sweeps(candles, analysis)

    assert not any(
        event.swing_kind is SwingKind.LOW and event.swing_index == 2
        for event in events
    )


def test_reference_touching_swing_levels_without_penetration_is_not_a_sweep() -> None:
    high_candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 15, 13, 14),
        )
    )
    low_candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (12, 13, 7, 12),
            (6, 11, 5, 6),
            (7, 12, 6, 7),
            (8, 10, 7, 8),
            (6, 7, 5, 6),
        )
    )

    # Each pivot at index 2 confirms at index 4. At index 5 the high-side
    # candle only touches 15, and the low-side candle only touches 5; neither
    # strictly penetrates its eligible swing.
    high_events = detect_liquidity_sweeps(
        high_candles, analyze_market_structure(high_candles)
    )
    low_events = detect_liquidity_sweeps(
        low_candles, analyze_market_structure(low_candles)
    )

    assert high_events == ()
    assert low_events == ()


def test_reference_swing_sweep_becomes_eligible_after_confirmation() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 16, 13, 14),
        )
    )

    # Index 2's high 15 is confirmed at 4 by the highs at 0, 1, 3, 4.
    # The detector activates it at 5 (confirmation + 1); the first possible
    # post-confirmation candidate at 5 makes a strict same-candle sweep.
    analysis = analyze_market_structure(candles)
    swing = next(
        swing
        for swing in analysis.swings
        if swing.kind is SwingKind.HIGH
    )
    events = detect_liquidity_sweeps(candles, analysis)

    assert (swing.index, swing.price, swing.confirmed_at_index) == (2, 15, 4)
    assert [(event.index, event.swing_index) for event in events] == [(5, 2)]


def test_reference_each_swing_identity_emits_only_one_sweep() -> None:
    candles = candles_from_ohlc(
        (
            (10, 12, 8, 10),
            (10, 13, 7, 11),
            (14, 15, 9, 14),
            (10, 14, 6, 8),
            (9, 13, 8, 10),
            (14, 16, 13, 14),
            (14, 17, 13, 14),
        )
    )

    # The high pivot at index 2 confirms at 4. Both indices 5 and 6 strictly
    # penetrate 15 and close below it, but both refer to that same swing id.
    analysis = analyze_market_structure(candles)
    events = detect_liquidity_sweeps(candles, analysis)

    assert [
        (event.index, event.swing_kind, event.swing_index, event.swing_price)
        for event in events
    ] == [(5, SwingKind.HIGH, 2, 15)]
