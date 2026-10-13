import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from tradiopro_analysis import main
from tradiopro_analysis.analysis_pipeline import AnalysisPipelineResult
from tradiopro_analysis.liquidity_sweeps import LiquiditySweepEvent
from tradiopro_analysis.market_structure import (
    AnalysisResult,
    Candle,
    Direction,
    EventKind,
    StructureEvent,
    Swing,
    SwingKind,
    TrendState,
)
from tradiopro_analysis.risk_validation import (
    ProposedTrade,
    TradeField,
    TradeValidationCode,
    TradeValidationError,
    TradeValidationResult,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def candle_payload(
    index: int,
    *,
    open_: object = 10,
    high: object = 12,
    low: object = 8,
    close: object = 10,
    volume: object = 100,
    timestamp: str | None = None,
) -> dict[str, object]:
    if timestamp is None:
        timestamp = (
            datetime(2025, 1, 1, tzinfo=timezone.utc)
            + timedelta(minutes=index)
        ).isoformat()
    return {
        "timestamp": timestamp,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def analysis_payload(
    *,
    trade: dict[str, object] | None = None,
    candles: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if candles is None:
        candles = [candle_payload(index) for index in range(9)]
        candles[2]["high"] = 15
        candles[5] = candle_payload(
            5, open_=14, high=16, low=13, close=14
        )
    if trade is None:
        trade = {
            "direction": "long",
            "entry_price": 100,
            "stop_loss_price": 95,
            "take_profit_price": 110,
        }
    return {"candles": candles, "trade": trade}


async def post_analysis(
    payload: dict[str, object],
    *,
    raise_app_exceptions: bool = True,
    content: str | None = None,
) -> Any:
    async with AsyncClient(
        transport=ASGITransport(
            app=main.app, raise_app_exceptions=raise_app_exceptions
        ),
        base_url="http://test",
    ) as client:
        if content is not None:
            return await client.post(
                "/analysis",
                content=content,
                headers={"Content-Type": "application/json"},
            )
        return await client.post("/analysis", json=payload)


@pytest.mark.anyio
async def test_analysis_endpoint_runs_real_pipeline_and_serializes_full_response() -> None:
    response = await post_analysis(analysis_payload())

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "market_structure",
        "liquidity_sweeps",
        "trade_validation",
    }

    structure = body["market_structure"]
    assert set(structure) == {"swings", "events", "trend"}
    assert structure["trend"] == "uninitialized"
    assert isinstance(structure["swings"], list)
    assert isinstance(structure["events"], list)
    swing = next(item for item in structure["swings"] if item["index"] == 2)
    assert set(swing) == {
        "kind",
        "index",
        "timestamp",
        "price",
        "label",
        "confirmed_at_index",
        "confirmed_at",
    }
    assert swing["kind"] == "high"
    assert datetime.fromisoformat(swing["timestamp"].replace("Z", "+00:00")) == (
        datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc)
    )
    assert datetime.fromisoformat(
        swing["confirmed_at"].replace("Z", "+00:00")
    ) == datetime(2025, 1, 1, 0, 4, tzinfo=timezone.utc)
    assert swing["label"] is None

    assert len(body["liquidity_sweeps"]) == 1
    sweep = body["liquidity_sweeps"][0]
    assert set(sweep) == {
        "kind",
        "direction",
        "index",
        "timestamp",
        "swing_kind",
        "swing_index",
        "swing_price",
        "penetration_price",
        "rejection_close",
    }
    assert sweep["kind"] == "liquidity_sweep"
    assert sweep["direction"] == "bearish"
    assert sweep["index"] == 5
    assert datetime.fromisoformat(sweep["timestamp"].replace("Z", "+00:00")) == (
        datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
    )
    assert sweep["swing_kind"] == "high"

    validation = body["trade_validation"]
    assert set(validation) == {
        "is_valid",
        "errors",
        "risk_distance",
        "reward_distance",
        "reward_to_risk_ratio",
    }
    assert validation == {
        "is_valid": True,
        "errors": [],
        "risk_distance": 5,
        "reward_distance": 10,
        "reward_to_risk_ratio": 2,
    }


@pytest.mark.anyio
async def test_optional_result_fields_serialize_as_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    swing = Swing(SwingKind.HIGH, 2, timestamp, 15, None, 4, timestamp)
    event = StructureEvent(
        EventKind.AMBIGUOUS_BREAK, None, 5, timestamp, None, None
    )
    result = AnalysisPipelineResult(
        market_structure=AnalysisResult(
            swings=(swing,), events=(event,), trend=TrendState.AMBIGUOUS
        ),
        liquidity_sweeps=(),
        trade_validation=TradeValidationResult(
            False,
            (
                TradeValidationError(
                    TradeField.ENTRY_PRICE, TradeValidationCode.MISSING_VALUE
                ),
            ),
            None,
            None,
            None,
        ),
    )
    monkeypatch.setattr(main, "analyze_market_and_trade", lambda candles, trade: result)

    response = await post_analysis(analysis_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["market_structure"]["swings"][0]["label"] is None
    assert body["market_structure"]["events"][0]["direction"] is None
    assert body["market_structure"]["events"][0]["level_price"] is None
    assert body["market_structure"]["events"][0]["level_index"] is None
    assert body["trade_validation"]["risk_distance"] is None
    assert body["trade_validation"]["reward_distance"] is None
    assert body["trade_validation"]["reward_to_risk_ratio"] is None


@pytest.mark.anyio
async def test_malformed_json_and_request_structures_return_422() -> None:
    malformed_json = await post_analysis({}, content="{")
    assert malformed_json.status_code == 422

    for payload in (
        {},
        {"candles": [], "trade": {}},
        {"candles": [candle_payload(0)], "trade": []},
        {
            "candles": [{**candle_payload(0), "extra": "not allowed"}],
            "trade": {},
        },
        {
            "candles": [candle_payload(0)],
            "trade": {},
            "unexpected": True,
        },
    ):
        response = await post_analysis(payload)
        assert response.status_code == 422


@pytest.mark.anyio
async def test_candle_domain_validation_returns_422() -> None:
    too_few = await post_analysis(
        analysis_payload(candles=[candle_payload(index) for index in range(4)])
    )
    assert too_few.status_code == 422
    assert "at least five candles" in too_few.json()["detail"]

    naive = [candle_payload(index) for index in range(5)]
    naive[2]["timestamp"] = "2025-01-01T00:02:00"
    response = await post_analysis(analysis_payload(candles=naive))
    assert response.status_code == 422

    unordered = [candle_payload(index) for index in range(5)]
    unordered[3]["timestamp"] = unordered[2]["timestamp"]
    response = await post_analysis(analysis_payload(candles=unordered))
    assert response.status_code == 422
    assert "strictly increasing" in response.json()["detail"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", True),
        ("high", "12"),
        ("low", float("nan")),
        ("close", float("inf")),
        ("volume", float("-inf")),
        ("open", 0),
        ("close", -1),
        ("volume", -1),
        ("low", 11),
        ("high", 9),
    ],
)
async def test_invalid_candle_numeric_and_ohlc_values_return_422(
    field: str, value: object
) -> None:
    candles = [candle_payload(index) for index in range(5)]
    candles[2][field] = value

    payload = analysis_payload(candles=candles)
    content = (
        json.dumps(payload, allow_nan=True)
        if isinstance(value, float) and not math.isfinite(value)
        else None
    )
    response = await post_analysis(payload, content=content)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_numeric_timestamp_is_rejected() -> None:
    candles = [candle_payload(index) for index in range(5)]
    candles[0]["timestamp"] = 1735689600

    response = await post_analysis(analysis_payload(candles=candles))

    assert response.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["high", "volume"])
async def test_inexact_large_candle_integers_are_rejected(
    field: str,
) -> None:
    candles = [candle_payload(index) for index in range(5)]
    candles[2][field] = 2**53 + 1

    response = await post_analysis(analysis_payload(candles=candles))

    assert response.status_code == 422
    assert "cannot be represented exactly" in str(response.json()["detail"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("trade", "code"),
    [
        (
            {"direction": "long", "entry_price": True, "stop_loss_price": 95, "take_profit_price": 110},
            "boolean_not_allowed",
        ),
        (
            {"direction": "long", "entry_price": "100", "stop_loss_price": 95, "take_profit_price": 110},
            "non_numeric",
        ),
        (
            {"direction": "long", "stop_loss_price": 95, "take_profit_price": 110},
            "missing_value",
        ),
        (
            {"direction": "LONG", "entry_price": 100, "stop_loss_price": 95, "take_profit_price": 110},
            "invalid_direction",
        ),
        (
            {
                "direction": "long",
                "entry_price": 2**53 + 1,
                "stop_loss_price": 2**53 - 1,
                "take_profit_price": 2**53 + 3,
            },
            "integer_not_exactly_representable",
        ),
        (
            {
                "direction": "long",
                "entry_price": 10**1000,
                "stop_loss_price": 1,
                "take_profit_price": 2,
            },
            "integer_out_of_float_range",
        ),
        (
            {"direction": "long", "entry_price": 100, "stop_loss_price": 101, "take_profit_price": 110},
            "invalid_price_order",
        ),
    ],
)
async def test_invalid_trade_values_reach_domain_validator(
    trade: dict[str, object], code: str
) -> None:
    response = await post_analysis(analysis_payload(trade=trade))

    assert response.status_code == 200
    body = response.json()
    assert body["market_structure"]["swings"]
    assert len(body["liquidity_sweeps"]) == 1
    validation = body["trade_validation"]
    assert validation["is_valid"] is False
    assert any(error["code"] == code for error in validation["errors"])
    assert validation["risk_distance"] is None
    assert validation["reward_distance"] is None
    assert validation["reward_to_risk_ratio"] is None


@pytest.mark.anyio
async def test_unexpected_pipeline_exception_is_not_a_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(candles: object, trade: object) -> AnalysisPipelineResult:
        raise RuntimeError("internal failure")

    monkeypatch.setattr(main, "analyze_market_and_trade", fail)

    response = await post_analysis(
        analysis_payload(),
        raise_app_exceptions=False,
    )

    assert response.status_code == 500


@pytest.mark.anyio
async def test_cors_preflight_allows_post_from_configured_frontend_origin() -> None:
    origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/analysis",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "POST" in response.headers["access-control-allow-methods"]


@pytest.mark.anyio
async def test_health_and_disabled_docs_behavior_remain_unchanged() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        health = await client.get("/health")
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert docs.status_code == 404
    assert openapi.status_code == 404
