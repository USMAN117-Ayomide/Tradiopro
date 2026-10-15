from historical_reference_cases import REFERENCE_CASES
from tradiopro_analysis.liquidity_sweeps import detect_liquidity_sweeps
from tradiopro_analysis.market_structure import analyze_market_structure


def test_historical_reference_cases_match_independent_expectations() -> None:
    assert len(REFERENCE_CASES) == 1

    for case in REFERENCE_CASES:
        analysis = analyze_market_structure(case.candles)
        sweeps = detect_liquidity_sweeps(case.candles, analysis)

        assert [
            (
                swing.kind,
                swing.index,
                swing.timestamp,
                swing.price,
                swing.label,
                swing.confirmed_at_index,
                swing.confirmed_at,
            )
            for swing in analysis.swings
        ] == [
            (
                swing.kind,
                swing.index,
                swing.timestamp,
                swing.price,
                swing.label,
                swing.confirmed_at_index,
                swing.confirmed_at,
            )
            for swing in case.expected_swings
        ]
        assert [
            (
                event.kind,
                event.direction,
                event.index,
                event.timestamp,
                event.level_price,
                event.level_index,
            )
            for event in analysis.events
        ] == [
            (
                event.kind,
                event.direction,
                event.index,
                event.timestamp,
                event.level_price,
                event.level_index,
            )
            for event in case.expected_structure_events
        ]
        assert [
            (
                event.kind,
                event.direction,
                event.index,
                event.timestamp,
                event.swing_kind,
                event.swing_index,
                event.swing_price,
                event.penetration_price,
                event.rejection_close,
            )
            for event in sweeps
        ] == [
            (
                event.kind,
                event.direction,
                event.index,
                event.timestamp,
                event.swing_kind,
                event.swing_index,
                event.swing_price,
                event.penetration_price,
                event.rejection_close,
            )
            for event in case.expected_sweeps
        ]
        assert analysis.trend is case.expected_trend
