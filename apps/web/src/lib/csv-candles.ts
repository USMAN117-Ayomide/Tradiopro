import type { AnalysisCandleRequest } from "@/lib/analysis-api";

export const CSV_MAX_FILE_BYTES = 2 * 1024 * 1024;
export const CSV_MAX_DATA_ROWS = 5000;
export const CSV_MAX_REPORTED_ERRORS = 100;

export const CSV_COLUMNS = [
  "timestamp",
  "open",
  "high",
  "low",
  "close",
  "volume",
] as const;

export type CsvColumn = (typeof CSV_COLUMNS)[number];

export interface CsvValidationError {
  line: number;
  column?: CsvColumn | "header" | "record";
  message: string;
}

export interface CsvImportSuccess {
  valid: true;
  candles: AnalysisCandleRequest[];
  errors: [];
  omittedErrorCount: 0;
}

export interface CsvImportFailure {
  valid: false;
  candles: null;
  errors: CsvValidationError[];
  omittedErrorCount: number;
}

export type CsvImportResult = CsvImportSuccess | CsvImportFailure;

interface CsvRecord {
  fields: string[];
  line: number;
  hasContent: boolean;
}

interface CsvSyntaxError {
  line: number;
  message: string;
}

const decimalPattern =
  /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const timestampPattern =
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

function parseDecimal(value: string): number | null {
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

function parseTimestamp(value: string): string | null {
  const match = timestampPattern.exec(value);
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
    (fraction.length > 0 && fraction.length > 3) ||
    day < 1 ||
    day > daysInMonth[month - 1]
  ) {
    return null;
  }

  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  const normalized = new Date(parsed);
  const normalizedYear = normalized.getUTCFullYear();
  if (normalizedYear < 1 || normalizedYear > 9999) {
    return null;
  }
  return normalized.toISOString();
}

function scanRecords(
  text: string,
  onRecord: (record: CsvRecord) => boolean,
): CsvSyntaxError | null {
  let fields: string[] = [];
  let field = "";
  let state: "start" | "unquoted" | "quoted" | "after-quote" = "start";
  let line = 1;
  let recordLine = 1;
  let hasContent = false;
  let stopped = false;

  function finishField() {
    fields.push(field);
    field = "";
    state = "start";
  }

  function finishRecord(): boolean {
    finishField();
    if (hasContent && !onRecord({ fields, line: recordLine, hasContent })) {
      stopped = true;
      return false;
    }
    fields = [];
    hasContent = false;
    recordLine = line + 1;
    return true;
  }

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    const isNewline = character === "\r" || character === "\n";
    const newlineLength =
      character === "\r" && text[index + 1] === "\n" ? 2 : 1;

    if (state === "quoted") {
      if (character === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          state = "after-quote";
        }
      } else if (isNewline) {
        field += "\n";
        line += 1;
        index += newlineLength - 1;
      } else {
        field += character;
      }
      continue;
    }

    if (state === "after-quote") {
      if (character === ",") {
        finishField();
        hasContent = true;
      } else if (isNewline) {
        if (!finishRecord()) {
          return null;
        }
        line += 1;
        index += newlineLength - 1;
      } else {
        return { line, message: "Unexpected character after a closing quote." };
      }
      continue;
    }

    if (isNewline) {
      if (!finishRecord()) {
        return null;
      }
      line += 1;
      index += newlineLength - 1;
    } else if (character === ",") {
      finishField();
      hasContent = true;
    } else if (state === "start" && character === '"') {
      state = "quoted";
      hasContent = true;
    } else if (character === '"') {
      return { line, message: "A quote may only begin a field." };
    } else {
      field += character;
      state = "unquoted";
      hasContent = true;
    }
  }

  if (state === "quoted") {
    return { line, message: "Unterminated quoted field." };
  }
  if (!stopped && (hasContent || fields.length > 0 || field.length > 0)) {
    finishRecord();
  }
  return null;
}

function failure(
  errors: CsvValidationError[],
  omittedErrorCount: number,
): CsvImportFailure {
  return { valid: false, candles: null, errors, omittedErrorCount };
}

export function parseCsvCandles(input: string): CsvImportResult {
  const text = input.startsWith("\uFEFF") ? input.slice(1) : input;
  const byteLength = new TextEncoder().encode(input).byteLength;
  if (byteLength > CSV_MAX_FILE_BYTES) {
    return failure(
      [{ line: 1, column: "record", message: "File exceeds the 2 MiB limit." }],
      0,
    );
  }

  const errors: CsvValidationError[] = [];
  let omittedErrorCount = 0;
  const addError = (error: CsvValidationError) => {
    if (errors.length < CSV_MAX_REPORTED_ERRORS) {
      errors.push(error);
    } else {
      omittedErrorCount += 1;
    }
  };

  let headerMap: Map<CsvColumn, number> | null = null;
  let rowCount = 0;
  let previousTimestamp: number | null = null;
  const candles: AnalysisCandleRequest[] = [];

  const syntaxError = scanRecords(text, (record) => {
    if (!headerMap) {
      const normalizedHeaders = record.fields.map((value) =>
        value.trim().toLowerCase(),
      );
      const duplicates = normalizedHeaders.filter(
        (value, index) => normalizedHeaders.indexOf(value) !== index,
      );
      const missing = CSV_COLUMNS.filter(
        (column) => !normalizedHeaders.includes(column),
      );
      const extra = normalizedHeaders.filter(
        (value) => !CSV_COLUMNS.includes(value as CsvColumn),
      );
      if (
        duplicates.length > 0 ||
        missing.length > 0 ||
        extra.length > 0 ||
        normalizedHeaders.length !== CSV_COLUMNS.length
      ) {
        addError({
          line: record.line,
          column: "header",
          message: [
            missing.length > 0 ? `Missing columns: ${missing.join(", ")}.` : "",
            extra.length > 0 ? `Unexpected columns: ${extra.join(", ")}.` : "",
            duplicates.length > 0 ? "Duplicate columns are not allowed." : "",
          ]
            .filter(Boolean)
            .join(" "),
        });
        return false;
      }
      headerMap = new Map(
        CSV_COLUMNS.map((column) => [
          column,
          normalizedHeaders.indexOf(column),
        ]),
      );
      return true;
    }

    rowCount += 1;
    if (rowCount > CSV_MAX_DATA_ROWS) {
      addError({
        line: record.line,
        column: "record",
        message: "File exceeds the 5,000 data-row limit.",
      });
      return false;
    }
    if (record.fields.length !== CSV_COLUMNS.length) {
      addError({
        line: record.line,
        column: "record",
        message: `Expected ${CSV_COLUMNS.length} fields but found ${record.fields.length}.`,
      });
      return true;
    }

    const value = (column: CsvColumn) =>
      record.fields[headerMap?.get(column) ?? -1];
    const timestampText = value("timestamp");
    const timestamp = parseTimestamp(timestampText);
    if (timestamp === null) {
      addError({
        line: record.line,
        column: "timestamp",
        message:
          "Expected a valid timezone-aware ISO-8601 timestamp with at most millisecond precision.",
      });
    }

    const numericValues = new Map<CsvColumn, number>();
    for (const column of ["open", "high", "low", "close", "volume"] as const) {
      const parsed = parseDecimal(value(column));
      if (parsed === null) {
        addError({
          line: record.line,
          column,
          message:
            "Expected a finite decimal number exactly representable by this browser.",
        });
      } else {
        numericValues.set(column, parsed);
      }
    }

    const open = numericValues.get("open");
    const high = numericValues.get("high");
    const low = numericValues.get("low");
    const close = numericValues.get("close");
    const volume = numericValues.get("volume");
    for (const column of ["open", "high", "low", "close"] as const) {
      const price = numericValues.get(column);
      if (price !== undefined && price <= 0) {
        addError({
          line: record.line,
          column,
          message: `${column[0].toUpperCase()}${column.slice(1)} price must be positive.`,
        });
      }
    }
    if (
      open !== undefined &&
      high !== undefined &&
      low !== undefined &&
      close !== undefined &&
      volume !== undefined
    ) {
      if (volume < 0) {
        addError({
          line: record.line,
          column: "volume",
          message: "Volume cannot be negative.",
        });
      }
      if (low > open || low > close) {
        addError({
          line: record.line,
          column: "low",
          message: "Low cannot exceed open or close.",
        });
      }
      if (high < open || high < close) {
        addError({
          line: record.line,
          column: "high",
          message: "High cannot be below open or close.",
        });
      }
      if (low > high) {
        addError({
          line: record.line,
          column: "low",
          message: "Low cannot exceed high.",
        });
      }
    }

    if (timestamp !== null) {
      const currentTime = Date.parse(timestamp);
      if (previousTimestamp !== null) {
        if (currentTime === previousTimestamp) {
          addError({
            line: record.line,
            column: "timestamp",
            message: "Timestamp duplicates the previous candle instant.",
          });
        } else if (currentTime < previousTimestamp) {
          addError({
            line: record.line,
            column: "timestamp",
            message: "Timestamps must be strictly chronological; rows are not sorted automatically.",
          });
        }
      }
      previousTimestamp = currentTime;
    }

    if (
      timestamp !== null &&
      open !== undefined &&
      high !== undefined &&
      low !== undefined &&
      close !== undefined &&
      volume !== undefined
    ) {
      candles.push({ timestamp, open, high, low, close, volume });
    }
    return true;
  });

  if (syntaxError) {
    addError({
      line: syntaxError.line,
      column: "record",
      message: syntaxError.message,
    });
    return failure(errors, omittedErrorCount);
  }
  if (!headerMap) {
    addError({
      line: 1,
      column: "header",
      message: "CSV must include the six required column headers.",
    });
    return failure(errors, omittedErrorCount);
  }
  if (rowCount < 5) {
    addError({
      line: 1,
      column: "record",
      message: "At least five candle rows are required.",
    });
  }
  if (errors.length > 0 || omittedErrorCount > 0 || candles.length !== rowCount) {
    return failure(errors, omittedErrorCount);
  }
  return { valid: true, candles, errors: [], omittedErrorCount: 0 };
}

export type CandleSource = "manual" | "csv";

export function selectAnalysisCandles(
  source: CandleSource,
  manualCandles: AnalysisCandleRequest[],
  importedCandles: AnalysisCandleRequest[] | null,
): AnalysisCandleRequest[] {
  if (source === "manual") {
    return manualCandles;
  }
  if (importedCandles === null) {
    throw new Error("Select a valid CSV import before running analysis.");
  }
  return importedCandles;
}
