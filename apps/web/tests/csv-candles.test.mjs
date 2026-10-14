/* global process, console */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { TextEncoder } from "node:util";
import ts from "typescript";

const validationModule = loadTypeScriptModule(
  path.resolve(process.cwd(), "src/lib/candle-validation.ts"),
);
const parserModule = loadTypeScriptModule(
  path.resolve(process.cwd(), "src/lib/csv-candles.ts"),
  { "@/lib/candle-validation": validationModule },
  { TextEncoder },
);
const { parseCsvCandles, CSV_MAX_DATA_ROWS, CSV_MAX_FILE_BYTES } =
  parserModule;

function loadTypeScriptModule(filename, dependencies = {}, context = {}) {
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(
    output,
    {
      module,
      exports: module.exports,
      require: (specifier) => {
        if (!(specifier in dependencies)) {
          throw new Error(`Unexpected module dependency: ${specifier}`);
        }
        return dependencies[specifier];
      },
      ...context,
    },
    { filename },
  );
  return module.exports;
}

let fetchHandler = async () => {
  throw new Error("Unexpected analysis API request.");
};
const api = loadTypeScriptModule(
  path.resolve(process.cwd(), "src/lib/analysis-api.ts"),
  {},
  {
    process: { env: { NEXT_PUBLIC_ANALYSIS_API_URL: "http://analysis.test" } },
    fetch: (...args) => fetchHandler(...args),
  },
);
const workflow = loadTypeScriptModule(
  path.resolve(process.cwd(), "src/lib/analysis-workflow.ts"),
  {
    "@/lib/analysis-api": api,
    "@/lib/csv-candles": parserModule,
    "@/lib/candle-validation": validationModule,
  },
);
const {
  candleTimestampInstant,
  manualTimestampToUtc,
  parseCandleNumber,
  validateCandleSeries,
} = validationModule;

const tests = [];

function test(name, run) {
  tests.push({ name, run });
}

function isoMinute(index) {
  return new Date(Date.UTC(2025, 0, 1, 0, index)).toISOString();
}

function candle(
  index,
  { timestamp = isoMinute(index), open = "10", high = "12", low = "8", close = "10", volume = "100" } = {},
) {
  return [timestamp, open, high, low, close, volume];
}

function requestCandle(index, overrides = {}) {
  return {
    timestamp: isoMinute(index),
    open: 10,
    high: 12,
    low: 8,
    close: 10,
    volume: 100,
    ...overrides,
  };
}

function csv(rows, { header = "timestamp,open,high,low,close,volume", newline = "\n", trailingNewline = false } = {}) {
  return [
    header,
    ...rows.map((row) => row.join(",")),
  ].join(newline) + (trailingNewline ? newline : "");
}

function assertInvalid(input) {
  const result = parseCsvCandles(input);
  assert.equal(result.valid, false);
  assert.equal(result.candles, null);
  return result;
}

function rowError(result, line, column) {
  return result.errors.find(
    (error) => error.line === line && error.column === column,
  );
}

test("accepts a valid five-candle CSV", () => {
  const result = parseCsvCandles(csv(Array.from({ length: 5 }, (_, i) => candle(i))));
  assert.equal(result.valid, true);
  assert.equal(result.candles.length, 5);
  assert.equal(result.candles[0].timestamp, "2025-01-01T00:00:00.000Z");
});

test("strips BOM and normalizes header whitespace and case", () => {
  const result = parseCsvCandles(
    `\uFEFF Timestamp , OPEN , High, low,Close, Volume\n${Array.from({ length: 5 }, (_, i) => candle(i)).map((row) => row.join(",")).join("\n")}`,
  );
  assert.equal(result.valid, true);
});

test("accepts reordered columns", () => {
  const rows = Array.from({ length: 5 }, (_, i) => {
    const values = candle(i);
    return [values[5], values[2], values[0], values[4], values[1], values[3]];
  });
  const result = parseCsvCandles(
    csv(rows, { header: "volume,high,timestamp,close,open,low" }),
  );
  assert.equal(result.valid, true);
  assert.equal(result.candles[0].open, 10);
});

test("accepts quoted fields, escaped quotes, and quoted commas syntactically", () => {
  const rows = Array.from({ length: 5 }, (_, i) => candle(i));
  rows[0][1] = '"10"';
  rows[1][5] = '"1,000"';
  rows[2][5] = '"1""0"';
  const result = assertInvalid(csv(rows));
  assert.ok(rowError(result, 3, "volume"));
  assert.ok(rowError(result, 4, "volume"));
  assert.ok(result.errors.every((error) => error.column !== "record"));
});

test("accepts CRLF, LF, and CR record endings", () => {
  const rows = Array.from({ length: 5 }, (_, i) => candle(i));
  for (const newline of ["\r\n", "\n", "\r"]) {
    assert.equal(parseCsvCandles(csv(rows, { newline })).valid, true);
  }
});

test("ignores completely empty records but rejects whitespace-only records", () => {
  const rows = Array.from({ length: 5 }, (_, i) => candle(i).join(","));
  const withBlank = `timestamp,open,high,low,close,volume\n\n${rows.join("\n")}\n`;
  assert.equal(parseCsvCandles(withBlank).valid, true);
  const withWhitespace = `timestamp,open,high,low,close,volume\n   \n${rows.join("\n")}`;
  const result = assertInvalid(withWhitespace);
  assert.ok(rowError(result, 2, "record"));
});

test("rejects malformed quoting and never returns partial candles", () => {
  const rows = Array.from({ length: 5 }, (_, i) => candle(i));
  const goodPrefix = csv(rows.slice(0, 2));
  for (const malformed of [
    `${goodPrefix}\n"unterminated`,
    `${goodPrefix}\n2025-01-01T00:02:00Z,1"0,12,8,10,100`,
    `${goodPrefix}\n"2025-01-01T00:02:00Z"x,10,12,8,10,100`,
  ]) {
    const result = assertInvalid(malformed);
    assert.ok(result.errors.some((error) => error.column === "record"));
  }
});

test("reports physical source lines after quoted embedded newlines", () => {
  const rows = Array.from({ length: 5 }, (_, i) => candle(i));
  rows[0][0] = '"not a timestamp\nstill not a timestamp"';
  rows[1][5] = "bad";
  const result = assertInvalid(csv(rows));
  assert.ok(rowError(result, 2, "timestamp"));
  assert.ok(rowError(result, 4, "volume"));
});

test("rejects missing, extra, and duplicate headers", () => {
  const validRows = Array.from({ length: 5 }, (_, i) => candle(i));
  for (const header of [
    "timestamp,open,high,low,close",
    "timestamp,open,high,low,close,volume,extra",
    "timestamp,open,high,low,close,OPEN",
  ]) {
    const result = assertInvalid(csv(validRows, { header }));
    assert.ok(rowError(result, 1, "header"));
  }
});

test("rejects invalid calendar dates and timezone-naive timestamps", () => {
  for (const timestamp of [
    "2025-02-29T00:00:00Z",
    "2025-02-30T00:00:00Z",
    "0100-02-29T00:00:00Z",
    "2025-01-01T00:00:00",
  ]) {
    const rows = Array.from({ length: 5 }, (_, i) =>
      candle(i, i === 0 ? { timestamp } : {}),
    );
    assert.ok(rowError(assertInvalid(csv(rows)), 2, "timestamp"));
  }
  const leapRows = Array.from({ length: 5 }, (_, i) =>
    candle(i, i === 0 ? { timestamp: "0004-02-29T00:00:00Z" } : {}),
  );
  assert.equal(parseCsvCandles(csv(leapRows)).valid, true);
});

test("rejects timestamp precision finer than milliseconds", () => {
  const rows = Array.from({ length: 5 }, (_, i) =>
    candle(i, i === 0 ? { timestamp: "2025-01-01T00:00:00.0001Z" } : {}),
  );
  assert.ok(rowError(assertInvalid(csv(rows)), 2, "timestamp"));
});

test("rejects duplicate instants expressed with different offsets", () => {
  const rows = Array.from({ length: 5 }, (_, i) =>
    candle(i, i === 1 ? { timestamp: "2025-01-01T01:00:00+01:00" } : {}),
  );
  const result = assertInvalid(csv(rows));
  assert.ok(rowError(result, 3, "timestamp")?.message.includes("duplicates"));
});

test("rejects out-of-order timestamps", () => {
  const rows = Array.from({ length: 5 }, (_, i) =>
    candle(i, i === 2 ? { timestamp: isoMinute(0) } : {}),
  );
  const result = assertInvalid(csv(rows));
  assert.ok(rowError(result, 4, "timestamp")?.message.includes("chronological"));
});

test("reports chronology errors after a row with invalid OHLCV", () => {
  const rows = Array.from({ length: 5 }, (_, i) =>
    candle(i, i === 1 ? { timestamp: isoMinute(2), high: "9" } : i === 2 ? { timestamp: isoMinute(1) } : {}),
  );
  const result = assertInvalid(csv(rows));
  assert.ok(rowError(result, 3, "high"));
  assert.ok(rowError(result, 4, "timestamp")?.message.includes("chronological"));
});

test("rejects malformed, non-finite, and inexact integer numeric values", () => {
  const invalidValues = [
    ['"1,000"', "comma"],
    ["NaN", "NaN"],
    ["Infinity", "Infinity"],
    ["1e309", "overflow"],
    ["9007199254740993", "inexact integer"],
  ];
  for (const [value] of invalidValues) {
    const rows = Array.from({ length: 5 }, (_, i) =>
      candle(i, i === 0 ? { volume: value } : {}),
    );
    assert.ok(rowError(assertInvalid(csv(rows)), 2, "volume"));
  }
  for (const value of ["9007199254740991", "9007199254740992", "9007199254740994"]) {
    const rows = Array.from({ length: 5 }, (_, i) =>
      candle(i, i === 0 ? { volume: value } : {}),
    );
    assert.equal(parseCsvCandles(csv(rows)).valid, true);
  }
});

test("associates each nonpositive OHLC error with its own column", () => {
  for (const column of ["open", "high", "low", "close"]) {
    const rows = Array.from({ length: 5 }, (_, i) =>
      candle(i, i === 0 ? { [column]: "-1" } : {}),
    );
    const result = assertInvalid(csv(rows));
    assert.ok(rowError(result, 2, column));
    assert.equal(result.errors.some((error) => error.column === "open" && column !== "open"), false);
  }
});

test("rejects inconsistent OHLC values and negative volume", () => {
  const invalidCases = [
    { high: "9" },
    { low: "11" },
    { close: "13" },
    { volume: "-1" },
  ];
  for (const invalid of invalidCases) {
    const rows = Array.from({ length: 5 }, (_, i) =>
      candle(i, i === 0 ? invalid : {}),
    );
    assertInvalid(csv(rows));
  }
});

test("rejects fewer than five data rows", () => {
  const result = assertInvalid(csv(Array.from({ length: 4 }, (_, i) => candle(i))));
  assert.ok(result.errors.some((error) => error.message.includes("At least five")));
});

test("accepts 5,000 rows and rejects 5,001 rows", () => {
  const rows = Array.from({ length: CSV_MAX_DATA_ROWS }, (_, i) => candle(i));
  assert.equal(parseCsvCandles(csv(rows)).valid, true);
  rows.push(candle(CSV_MAX_DATA_ROWS));
  const result = assertInvalid(csv(rows));
  assert.ok(result.errors.some((error) => error.message.includes("5,000")));
});

test("rejects files larger than 2 MiB before parsing", () => {
  const oversized = `timestamp,open,high,low,close,volume\n${" ".repeat(CSV_MAX_FILE_BYTES)}`;
  const result = assertInvalid(oversized);
  assert.ok(result.errors.some((error) => error.message.includes("2 MiB")));
});

test("caps reported validation errors and counts omitted errors", () => {
  const rows = Array.from({ length: 35 }, (_, i) =>
    candle(i, {
      timestamp: "not-a-time",
      open: "bad",
      high: "bad",
      low: "bad",
      close: "bad",
      volume: "bad",
    }),
  );
  const result = assertInvalid(csv(rows));
  assert.equal(result.errors.length, 100);
  assert.ok(result.omittedErrorCount > 0);
});

test("invalid rows and malformed syntax never expose partial candles", () => {
  const rows = Array.from({ length: 5 }, (_, i) => candle(i));
  rows[4][0] = '"unterminated';
  const result = assertInvalid(csv(rows));
  assert.equal(result.candles, null);
});

test("shared validation requires at least five candles", () => {
  assert.match(
    validateCandleSeries(Array.from({ length: 4 }, (_, index) => requestCandle(index)))[0].message,
    /at least 5 candles/,
  );
});

test("shared validation rejects duplicate and out-of-order instants", () => {
  const duplicate = Array.from({ length: 5 }, (_, index) => requestCandle(index));
  duplicate[2].timestamp = "2025-01-01T01:01:00+01:00";
  assert.match(
    validateCandleSeries(duplicate).find((issue) => issue.index === 2).message,
    /duplicates/,
  );

  const unordered = Array.from({ length: 5 }, (_, index) => requestCandle(index));
  unordered[3].timestamp = isoMinute(1);
  assert.match(
    validateCandleSeries(unordered).find((issue) => issue.index === 3).message,
    /chronological/,
  );
});

test("shared validation rejects invalid OHLC geometry and negative volume", () => {
  for (const [field, value] of [["high", 9], ["low", 11], ["open", 0], ["close", -1], ["volume", -1]]) {
    const candles = Array.from({ length: 5 }, (_, index) => requestCandle(index));
    candles[2][field] = value;
    assert.ok(validateCandleSeries(candles).some((issue) => issue.index === 2 && issue.field === field));
  }
  const zeroVolume = Array.from({ length: 5 }, (_, index) =>
    requestCandle(index, index === 2 ? { volume: 0 } : {}),
  );
  assert.equal(validateCandleSeries(zeroVolume).length, 0);
});

test("shared numeric parsing rejects empty, non-finite, and inexact integers", () => {
  for (const value of ["", " ", "NaN", "Infinity", "1e309", "9007199254740993"]) {
    assert.equal(parseCandleNumber(value), null);
  }
});

test("shared numeric parsing accepts fractional prices without rounding", () => {
  assert.equal(parseCandleNumber("1.23456789"), 1.23456789);
});

test("shared validation compares actual timestamp instants", () => {
  assert.equal(
    candleTimestampInstant("2025-01-01T01:00:00+01:00"),
    candleTimestampInstant("2025-01-01T00:00:00Z"),
  );
});

test("shared validation accepts timestamp boundaries and supported precision", () => {
  for (const timestamp of [
    "2025-01-01T23:59:59Z",
    "2025-01-01T23:59:59.123Z",
    "2024-02-29T12:30:45.123+05:30",
  ]) {
    assert.notEqual(candleTimestampInstant(timestamp), null);
  }
});

test("shared validation rejects out-of-range time and excess precision", () => {
  for (const timestamp of [
    "2025-01-01T24:00:00Z",
    "2025-01-01T23:60:00Z",
    "2025-01-01T23:59:60Z",
    "2025-01-01T23:59:59.1234Z",
    "2025-01-01T00:00:00+24:00",
    "2025-01-01T00:00:00+01:60",
  ]) {
    assert.equal(candleTimestampInstant(timestamp), null, timestamp);
  }
});

test("shared validation rejects impossible calendar dates", () => {
  for (const timestamp of [
    "2025-02-29T00:00:00Z",
    "2025-02-30T00:00:00Z",
    "0000-01-01T00:00:00Z",
  ]) {
    const candles = Array.from({ length: 5 }, (_, index) =>
      requestCandle(index, index === 2 ? { timestamp } : {}),
    );
    assert.ok(
      validateCandleSeries(candles).some(
        (issue) => issue.index === 2 && issue.field === "timestamp",
      ),
    );
  }

  assert.equal(
    candleTimestampInstant("2024-02-29T00:00:00Z"),
    Date.parse("2024-02-29T00:00:00Z"),
  );
});

test("manual datetime-local conversion retains browser-local interpretation", () => {
  const localValue = "2025-06-15T12:34";
  assert.equal(
    manualTimestampToUtc(localValue),
    new Date(localValue).toISOString(),
  );
});

test("invalid manual candle series cannot issue an analysis request", async () => {
  let requestCount = 0;
  fetchHandler = async () => {
    requestCount += 1;
    throw new Error("Unexpected API call.");
  };
  const invalidManual = Array.from({ length: 5 }, (_, index) => requestCandle(index));
  invalidManual[2].high = 9;
  await assert.rejects(
    workflow.analyzeSelectedCandles("manual", invalidManual, null, {}),
    /Candle 3 \(high\)/,
  );
  assert.equal(requestCount, 0);
});

test("oversized files are rejected without reading their content", async () => {
  let readCount = 0;
  const result = await workflow.readCsvFile({
    name: "large.csv",
    size: CSV_MAX_FILE_BYTES + 1,
    async text() {
      readCount += 1;
      return "";
    },
  });
  assert.equal(readCount, 0);
  assert.match(result.error, /2 MiB/);
});

test("file-reading failures return a visible import error", async () => {
  const result = await workflow.readCsvFile({
    name: "unreadable.csv",
    size: 10,
    async text() {
      throw new Error("read failed");
    },
  });
  assert.equal(result.result, null);
  assert.match(result.error, /could not be read or validated/);
});

test("replacement invalidates the previous import and ignores stale reads", async () => {
  const controller = new workflow.CsvImportController();
  const updates = [];
  const onChange = (current, reading) => updates.push({ current, reading });
  const validText = csv(Array.from({ length: 5 }, (_, i) => candle(i)));
  await controller.replace(
    { name: "first.csv", size: validText.length, text: async () => validText },
    onChange,
  );
  assert.equal(controller.current.filename, "first.csv");

  let finishSlowRead;
  const slowReplacement = controller.replace(
    {
      name: "slow.csv",
      size: 20,
      text: () => new Promise((resolve) => { finishSlowRead = resolve; }),
    },
    onChange,
  );
  assert.equal(controller.current, null);
  await controller.replace(
    {
      name: "invalid.csv",
      size: 20,
      text: async () => "timestamp,open,high,low,close,volume\nbad",
    },
    onChange,
  );
  assert.equal(controller.current.filename, "invalid.csv");
  assert.equal(controller.current.result.valid, false);
  finishSlowRead(validText);
  await slowReplacement;
  assert.equal(controller.current.filename, "invalid.csv");
  assert.ok(updates.some((update) => update.current === null && update.reading));
});

test("CSV reset clears the active import and invalidates pending completion", async () => {
  const controller = new workflow.CsvImportController();
  const validText = csv(Array.from({ length: 5 }, (_, i) => candle(i)));
  await controller.replace(
    { name: "valid.csv", size: validText.length, text: async () => validText },
    () => {},
  );
  controller.reset(() => {});
  assert.equal(controller.current, null);
  await assert.rejects(
    workflow.analyzeSelectedCandles("csv", [], null, {}),
    /valid CSV import/,
  );
});

test("selected CSV candles use the existing analysis client", async () => {
  const parsed = parseCsvCandles(csv(Array.from({ length: 5 }, (_, i) => candle(i))));
  assert.equal(parsed.valid, true);
  let request;
  fetchHandler = async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      async json() {
        return {
          market_structure: { swings: [], events: [], trend: "uninitialized" },
          liquidity_sweeps: [],
          trade_validation: {
            is_valid: false,
            errors: [],
            risk_distance: null,
            reward_distance: null,
            reward_to_risk_ratio: null,
          },
        };
      },
    };
  };
  await workflow.analyzeSelectedCandles("csv", [], parsed.candles, {});
  assert.equal(request.url, "http://analysis.test/analysis");
  assert.equal(request.options.method, "POST");
  assert.equal(JSON.parse(request.options.body).candles.length, 5);
});

test("invalid CSV cannot issue an analysis request", async () => {
  let requestCount = 0;
  fetchHandler = async () => {
    requestCount += 1;
    throw new Error("Unexpected analysis call.");
  };
  const parsed = parseCsvCandles("invalid");
  assert.equal(parsed.valid, false);
  await assert.rejects(
    workflow.analyzeSelectedCandles(
      "csv",
      [{ timestamp: isoMinute(0), open: 10, high: 12, low: 8, close: 10, volume: 100 }],
      parsed.valid ? parsed.candles : null,
      {},
    ),
    /valid CSV import/,
  );
  assert.equal(requestCount, 0);
});

test("manual source submits only manual candles through the existing client", async () => {
  const manual = Array.from({ length: 5 }, (_, index) => requestCandle(index));
  let postedCandles;
  fetchHandler = async (_url, options) => {
    postedCandles = JSON.parse(options.body).candles;
    return {
      ok: true,
      async json() {
        return {
          market_structure: { swings: [], events: [], trend: "uninitialized" },
          liquidity_sweeps: [],
          trade_validation: {
            is_valid: false,
            errors: [],
            risk_distance: null,
            reward_distance: null,
            reward_to_risk_ratio: null,
          },
        };
      },
    };
  };
  await workflow.analyzeSelectedCandles("manual", manual, [
    { ...manual[0], timestamp: isoMinute(5) },
  ], {});
  assert.deepEqual(postedCandles, manual);
});

let failed = 0;
for (const { name, run } of tests) {
  try {
    await run();
    console.log(`PASS ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`FAIL ${name}`);
    console.error(error);
  }
}

console.log(`\n${tests.length - failed}/${tests.length} tests passed`);
if (failed > 0) {
  process.exitCode = 1;
}
