export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface AnalysisCandleRequest {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ProposedTradeRequest {
  direction?: JsonValue;
  entry_price?: JsonValue;
  stop_loss_price?: JsonValue;
  take_profit_price?: JsonValue;
}

export interface AnalysisRequest {
  candles: AnalysisCandleRequest[];
  trade: ProposedTradeRequest;
}

export interface SwingResponse {
  kind: "high" | "low";
  index: number;
  timestamp: string;
  price: number;
  label: "HH" | "LH" | "EQH" | "HL" | "LL" | "EQL" | null;
  confirmed_at_index: number;
  confirmed_at: string;
}

export interface StructureEventResponse {
  kind:
    | "BOS"
    | "CHoCH"
    | "wick_penetration"
    | "ambiguous_break"
    | "unresolved_break";
  direction: "bullish" | "bearish" | null;
  index: number;
  timestamp: string;
  level_price: number | null;
  level_index: number | null;
}

export interface MarketStructureResponse {
  swings: SwingResponse[];
  events: StructureEventResponse[];
  trend: "uninitialized" | "bullish" | "bearish" | "ambiguous";
}

export interface LiquiditySweepResponse {
  kind: "liquidity_sweep";
  direction: "bullish" | "bearish";
  index: number;
  timestamp: string;
  swing_kind: "high" | "low";
  swing_index: number;
  swing_price: number;
  penetration_price: number;
  rejection_close: number;
}

export interface TradeValidationErrorResponse {
  field:
    | "direction"
    | "entry_price"
    | "stop_loss_price"
    | "take_profit_price"
    | "risk_distance"
    | "reward_distance"
    | "reward_to_risk_ratio";
  code:
    | "missing_value"
    | "invalid_direction"
    | "boolean_not_allowed"
    | "non_numeric"
    | "non_finite"
    | "non_positive"
    | "integer_not_exactly_representable"
    | "integer_out_of_float_range"
    | "zero_risk_distance"
    | "zero_reward_distance"
    | "invalid_price_order"
    | "arithmetic_overflow"
    | "reward_to_risk_underflow";
}

export interface TradeValidationResponse {
  is_valid: boolean;
  errors: TradeValidationErrorResponse[];
  risk_distance: number | null;
  reward_distance: number | null;
  reward_to_risk_ratio: number | null;
}

export interface AnalysisResponse {
  market_structure: MarketStructureResponse;
  liquidity_sweeps: LiquiditySweepResponse[];
  trade_validation: TradeValidationResponse;
}

export class AnalysisApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AnalysisApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function isOneOf<T extends string>(
  value: unknown,
  options: readonly T[],
): value is T {
  return typeof value === "string" && options.some((option) => option === value);
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}

function isSwing(value: unknown): value is SwingResponse {
  return (
    isRecord(value) &&
    isOneOf(value.kind, ["high", "low"]) &&
    isInteger(value.index) &&
    isString(value.timestamp) &&
    isFiniteNumber(value.price) &&
    (value.label === null ||
      isOneOf(value.label, ["HH", "LH", "EQH", "HL", "LL", "EQL"])) &&
    isInteger(value.confirmed_at_index) &&
    isString(value.confirmed_at)
  );
}

function isStructureEvent(value: unknown): value is StructureEventResponse {
  return (
    isRecord(value) &&
    isOneOf(value.kind, [
      "BOS",
      "CHoCH",
      "wick_penetration",
      "ambiguous_break",
      "unresolved_break",
    ]) &&
    (value.direction === null ||
      isOneOf(value.direction, ["bullish", "bearish"])) &&
    isInteger(value.index) &&
    isString(value.timestamp) &&
    isNullableNumber(value.level_price) &&
    (value.level_index === null || isInteger(value.level_index))
  );
}

function isLiquiditySweep(value: unknown): value is LiquiditySweepResponse {
  return (
    isRecord(value) &&
    value.kind === "liquidity_sweep" &&
    isOneOf(value.direction, ["bullish", "bearish"]) &&
    isInteger(value.index) &&
    isString(value.timestamp) &&
    isOneOf(value.swing_kind, ["high", "low"]) &&
    isInteger(value.swing_index) &&
    isFiniteNumber(value.swing_price) &&
    isFiniteNumber(value.penetration_price) &&
    isFiniteNumber(value.rejection_close)
  );
}

function isTradeValidationError(
  value: unknown,
): value is TradeValidationErrorResponse {
  return (
    isRecord(value) &&
    isOneOf(value.field, [
      "direction",
      "entry_price",
      "stop_loss_price",
      "take_profit_price",
      "risk_distance",
      "reward_distance",
      "reward_to_risk_ratio",
    ]) &&
    isOneOf(value.code, [
      "missing_value",
      "invalid_direction",
      "boolean_not_allowed",
      "non_numeric",
      "non_finite",
      "non_positive",
      "integer_not_exactly_representable",
      "integer_out_of_float_range",
      "zero_risk_distance",
      "zero_reward_distance",
      "invalid_price_order",
      "arithmetic_overflow",
      "reward_to_risk_underflow",
    ])
  );
}

function isAnalysisResponse(value: unknown): value is AnalysisResponse {
  if (!isRecord(value)) {
    return false;
  }

  const marketStructure = value.market_structure;
  const tradeValidation = value.trade_validation;
  return (
    isRecord(marketStructure) &&
    Array.isArray(marketStructure.swings) &&
    marketStructure.swings.every((item: unknown) => isSwing(item)) &&
    Array.isArray(marketStructure.events) &&
    marketStructure.events.every((item: unknown) => isStructureEvent(item)) &&
    isOneOf(marketStructure.trend, [
      "uninitialized",
      "bullish",
      "bearish",
      "ambiguous",
    ]) &&
    Array.isArray(value.liquidity_sweeps) &&
    value.liquidity_sweeps.every((item: unknown) => isLiquiditySweep(item)) &&
    isRecord(tradeValidation) &&
    typeof tradeValidation.is_valid === "boolean" &&
    Array.isArray(tradeValidation.errors) &&
    tradeValidation.errors.every((item: unknown) =>
      isTradeValidationError(item),
    ) &&
    isNullableNumber(tradeValidation.risk_distance) &&
    isNullableNumber(tradeValidation.reward_distance) &&
    isNullableNumber(tradeValidation.reward_to_risk_ratio)
  );
}

function responseErrorMessage(payload: unknown, status: number): string {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((item) => {
        if (typeof item !== "object" || item === null || !("msg" in item)) {
          return [];
        }
        const location =
          "loc" in item && Array.isArray(item.loc)
            ? `${item.loc.join(".")}: `
            : "";
        return [`${location}${String(item.msg)}`];
      });
      if (messages.length > 0) {
        return messages.join("; ");
      }
    }
  }

  return `Analysis request failed with HTTP ${status}.`;
}

export async function analyzeMarket(
  request: AnalysisRequest,
): Promise<AnalysisResponse> {
  const baseUrl = process.env.NEXT_PUBLIC_ANALYSIS_API_URL?.trim();
  if (!baseUrl) {
    throw new AnalysisApiError(
      "Set NEXT_PUBLIC_ANALYSIS_API_URL to the analysis service URL.",
    );
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/+$/, "")}/analysis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    throw new AnalysisApiError(
      "Could not connect to the analysis service. Check that it is running and the API URL is correct.",
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new AnalysisApiError(
      "The analysis service returned an invalid or empty JSON response.",
    );
  }

  if (!response.ok) {
    throw new AnalysisApiError(responseErrorMessage(payload, response.status));
  }

  if (!isAnalysisResponse(payload)) {
    throw new AnalysisApiError(
      "The analysis service returned a response that does not match the expected format.",
    );
  }

  return payload;
}
