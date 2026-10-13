import os
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator

from .analysis_pipeline import AnalysisPipelineResult, analyze_market_and_trade
from .liquidity_sweeps import LiquiditySweepKind
from .market_structure import (
    AnalysisResult,
    Candle,
    Direction,
    EventKind,
    StructureLabel,
    SwingKind,
    TrendState,
    _validate_candles,
)
from .risk_validation import (
    ProposedTrade,
    TradeField,
    TradeValidationCode,
)


class HealthResponse(BaseModel):
    status: str


class StrictRequestModel(BaseModel):
    class Config:
        extra = "forbid"


class CandleRequest(StrictRequestModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @validator("timestamp", pre=True)
    def timestamp_must_be_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO-8601 string")
        return value

    @validator("timestamp")
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @validator("open", "high", "low", "close", "volume", pre=True)
    def numeric_value_must_be_json_number(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("value must be a JSON number")
        try:
            converted = float(value)
        except OverflowError as exc:
            raise ValueError("value must be finite") from exc
        if type(value) is int and int(converted) != value:
            raise ValueError("integer value cannot be represented exactly as a float")
        return converted


class ProposedTradeRequest(StrictRequestModel):
    direction: Any = None
    entry_price: Any = None
    stop_loss_price: Any = None
    take_profit_price: Any = None


class AnalysisRequest(StrictRequestModel):
    candles: list[CandleRequest]
    trade: ProposedTradeRequest


class SwingResponse(BaseModel):
    kind: SwingKind
    index: int
    timestamp: datetime
    price: float
    label: StructureLabel | None
    confirmed_at_index: int
    confirmed_at: datetime


class StructureEventResponse(BaseModel):
    kind: EventKind
    direction: Direction | None
    index: int
    timestamp: datetime
    level_price: float | None
    level_index: int | None


class MarketStructureResponse(BaseModel):
    swings: tuple[SwingResponse, ...]
    events: tuple[StructureEventResponse, ...]
    trend: TrendState


class LiquiditySweepResponse(BaseModel):
    kind: LiquiditySweepKind
    direction: Direction
    index: int
    timestamp: datetime
    swing_kind: SwingKind
    swing_index: int
    swing_price: float
    penetration_price: float
    rejection_close: float


class TradeValidationErrorResponse(BaseModel):
    field: TradeField
    code: TradeValidationCode


class TradeValidationResponse(BaseModel):
    is_valid: bool
    errors: tuple[TradeValidationErrorResponse, ...]
    risk_distance: float | None
    reward_distance: float | None
    reward_to_risk_ratio: float | None


class AnalysisResponse(BaseModel):
    market_structure: MarketStructureResponse
    liquidity_sweeps: tuple[LiquiditySweepResponse, ...]
    trade_validation: TradeValidationResponse


def _candle_from_request(candle: CandleRequest) -> Candle:
    return Candle(
        timestamp=candle.timestamp,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
    )


def _analysis_response(result: AnalysisPipelineResult) -> AnalysisResponse:
    market_structure: AnalysisResult = result.market_structure
    return AnalysisResponse(
        market_structure=MarketStructureResponse(
            swings=tuple(
                SwingResponse(
                    kind=swing.kind,
                    index=swing.index,
                    timestamp=swing.timestamp,
                    price=swing.price,
                    label=swing.label,
                    confirmed_at_index=swing.confirmed_at_index,
                    confirmed_at=swing.confirmed_at,
                )
                for swing in market_structure.swings
            ),
            events=tuple(
                StructureEventResponse(
                    kind=event.kind,
                    direction=event.direction,
                    index=event.index,
                    timestamp=event.timestamp,
                    level_price=event.level_price,
                    level_index=event.level_index,
                )
                for event in market_structure.events
            ),
            trend=market_structure.trend,
        ),
        liquidity_sweeps=tuple(
            LiquiditySweepResponse(
                kind=sweep.kind.value,
                direction=sweep.direction,
                index=sweep.index,
                timestamp=sweep.timestamp,
                swing_kind=sweep.swing_kind,
                swing_index=sweep.swing_index,
                swing_price=sweep.swing_price,
                penetration_price=sweep.penetration_price,
                rejection_close=sweep.rejection_close,
            )
            for sweep in result.liquidity_sweeps
        ),
        trade_validation=TradeValidationResponse(
            is_valid=result.trade_validation.is_valid,
            errors=tuple(
                TradeValidationErrorResponse(
                    field=error.field,
                    code=error.code,
                )
                for error in result.trade_validation.errors
            ),
            risk_distance=result.trade_validation.risk_distance,
            reward_distance=result.trade_validation.reward_distance,
            reward_to_risk_ratio=result.trade_validation.reward_to_risk_ratio,
        ),
    )


app = FastAPI(
    title="Tradiopro Analysis API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/analysis", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest) -> AnalysisResponse:
    candles = [_candle_from_request(item) for item in request.candles]
    try:
        _validate_candles(candles)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    trade = ProposedTrade(
        direction=request.trade.direction,
        entry_price=request.trade.entry_price,
        stop_loss_price=request.trade.stop_loss_price,
        take_profit_price=request.trade.take_profit_price,
    )
    result = analyze_market_and_trade(candles, trade)
    return _analysis_response(result)
