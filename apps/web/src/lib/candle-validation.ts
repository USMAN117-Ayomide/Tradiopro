import type { AnalysisCandleRequest } from "@/lib/analysis-api";

export const MIN_CANDLE_COUNT = 5;

export type CandleValueField =
  | "timestamp"
  | "open"
  | "high"
  | "low"
  | "close"
  | "volume";

export interface CandleValidationIssue {
  index: number;
  field: CandleValueField;
  message: string;
}

const decimalPattern =
  /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const timezoneAwareTimestampPattern =
  /^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?:\.(\d+))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

function exactlyRepresentsInteger(value: string, number: number): boolean {
  const match = /^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if (!match) {
    return false;
  }

  const [, sign, whole, fraction = "", exponentText = "0"] = match;
  const exponent = Number(exponentText);
  let digits = `${whole}${fraction}`.replace(/^0+/, "");
  if (digits === "") {
    return number === 0;
  }
  if (!Number.isSafeInteger(exponent)) {
    return false;
  }

  let scale = exponent - fraction.length;
  while (digits.endsWith("0")) {
    digits = digits.slice(0, -1);
    scale += 1;
  }
  if (scale < 0) {
    return false;
  }

  const exactInteger =
    BigInt(`${sign}${digits}`) * BigInt(10) ** BigInt(scale);
  return exactInteger === BigInt(number);
}

export function parseCandleNumber(value: string): number | null {
  if (!decimalPattern.test(value)) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  if (Number.isInteger(parsed) && !exactlyRepresentsInteger(value, parsed)) {
    return null;
  }
  return parsed;
}

export function manualTimestampToUtc(value: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function timestampInstant(value: string): number | null {
  const match = timezoneAwareTimestampPattern.exec(value);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const fraction = match[7] ?? "";
  const daysInMonth = [
    31,
    year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    fraction.length > 3 ||
    day < 1 ||
    day > daysInMonth[month - 1]
  ) {
    return null;
  }

  const instant = Date.parse(value);
  if (!Number.isFinite(instant)) {
    return null;
  }
  const normalizedYear = new Date(instant).getUTCFullYear();
  return normalizedYear >= 1 && normalizedYear <= 9999 ? instant : null;
}

export function candleTimestampInstant(value: string): number | null {
  return timestampInstant(value);
}

export function validateCandleValues(
  candle: AnalysisCandleRequest,
  index: number,
): CandleValidationIssue[] {
  const issues: CandleValidationIssue[] = [];
  const numericFields = ["open", "high", "low", "close", "volume"] as const;

  for (const field of numericFields) {
    if (!Number.isFinite(candle[field])) {
      issues.push({
        index,
        field,
        message: "Value must be finite.",
      });
    }
  }
  if (numericFields.some((field) => !Number.isFinite(candle[field]))) {
    return issues;
  }

  for (const field of ["open", "high", "low", "close"] as const) {
    if (candle[field] <= 0) {
      issues.push({
        index,
        field,
        message: `${field[0].toUpperCase()}${field.slice(1)} price must be positive.`,
      });
    }
  }
  if (candle.volume < 0) {
    issues.push({
      index,
      field: "volume",
      message: "Volume cannot be negative.",
    });
  }
  if (candle.low > candle.open || candle.low > candle.close) {
    issues.push({
      index,
      field: "low",
      message: "Low cannot exceed open or close.",
    });
  }
  if (candle.high < candle.open || candle.high < candle.close) {
    issues.push({
      index,
      field: "high",
      message: "High cannot be below open or close.",
    });
  }
  if (candle.low > candle.high) {
    issues.push({
      index,
      field: "low",
      message: "Low cannot exceed high.",
    });
  }

  return issues;
}

export function validateCandleSeries(
  candles: AnalysisCandleRequest[],
): CandleValidationIssue[] {
  const issues: CandleValidationIssue[] = [];
  if (candles.length < MIN_CANDLE_COUNT) {
    issues.push({
      index: 0,
      field: "timestamp",
      message: `Enter at least ${MIN_CANDLE_COUNT} candles.`,
    });
  }

  let previousInstant: number | null = null;
  candles.forEach((candle, index) => {
    const instant = timestampInstant(candle.timestamp);
    if (instant === null) {
      issues.push({
        index,
        field: "timestamp",
        message: "Timestamp must be a valid timezone-aware date and time.",
      });
    } else {
      if (previousInstant !== null && instant <= previousInstant) {
        issues.push({
          index,
          field: "timestamp",
          message:
            instant === previousInstant
              ? "Timestamp duplicates the previous candle instant."
              : "Timestamps must be strictly chronological; rows are not sorted automatically.",
        });
      }
      previousInstant = instant;
    }
    issues.push(...validateCandleValues(candle, index));
  });

  return issues;
}

export function formatCandleValidationIssue(
  issue: CandleValidationIssue,
): string {
  return `Candle ${issue.index + 1} (${issue.field}): ${issue.message}`;
}
