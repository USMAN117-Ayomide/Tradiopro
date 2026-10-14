"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import {
  type AnalysisCandleRequest,
  type AnalysisResponse,
  type ProposedTradeRequest,
} from "@/lib/analysis-api";
import {
  analyzeSelectedCandles,
  CsvImportController,
  type CsvFileImport,
} from "@/lib/analysis-workflow";
import {
  CSV_COLUMNS,
  type CandleSource,
  type CsvColumn,
} from "@/lib/csv-candles";
import {
  manualTimestampToUtc,
  parseCandleNumber,
} from "@/lib/candle-validation";

interface CandleRow {
  id: number;
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

interface TradeFields {
  direction: string;
  entry_price: string;
  stop_loss_price: string;
  take_profit_price: string;
}

const candleFields = [
  ["timestamp", "Timestamp"],
  ["open", "Open"],
  ["high", "High"],
  ["low", "Low"],
  ["close", "Close"],
  ["volume", "Volume"],
] as const;

function emptyCandle(id: number): CandleRow {
  return {
    id,
    timestamp: "",
    open: "",
    high: "",
    low: "",
    close: "",
    volume: "",
  };
}

function numericInput(value: string, label: string): number {
  if (value.trim() === "") {
    throw new Error(`${label} is required.`);
  }

  const number = parseCandleNumber(value.trim());
  if (number === null) {
    if (Number.isInteger(Number(value.trim()))) {
      throw new Error(
        `${label} cannot be represented exactly in this browser.`,
      );
    }
    throw new Error(`${label} must be a finite number.`);
  }
  return number;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function displayMetric(value: number | null): string {
  return value === null ? "Not available" : String(value);
}

function manualCandleRequests(
  candles: CandleRow[],
): AnalysisCandleRequest[] {
  return candles.map((candle, index) => {
    const timestamp = manualTimestampToUtc(candle.timestamp);
    if (timestamp === null) {
      throw new Error(`Candle ${index + 1} needs a valid timestamp.`);
    }

    return {
      timestamp,
      open: numericInput(candle.open, `Candle ${index + 1} open`),
      high: numericInput(candle.high, `Candle ${index + 1} high`),
      low: numericInput(candle.low, `Candle ${index + 1} low`),
      close: numericInput(candle.close, `Candle ${index + 1} close`),
      volume: numericInput(candle.volume, `Candle ${index + 1} volume`),
    };
  });
}

function formatCsvColumn(column: CsvColumn | "header" | "record" | undefined) {
  return column ? ` (${column})` : "";
}

export default function AnalysisForm() {
  const [candles, setCandles] = useState<CandleRow[]>([
    emptyCandle(0),
    emptyCandle(1),
    emptyCandle(2),
    emptyCandle(3),
    emptyCandle(4),
  ]);
  const [nextCandleId, setNextCandleId] = useState(5);
  const [candleSource, setCandleSource] = useState<CandleSource>("manual");
  const [csvImport, setCsvImport] = useState<CsvFileImport | null>(null);
  const [isReadingCsv, setIsReadingCsv] = useState(false);
  const [csvImportStatus, setCsvImportStatus] = useState("");
  const [csvImportController] = useState(() => new CsvImportController());
  const [trade, setTrade] = useState<TradeFields>({
    direction: "",
    entry_price: "",
    stop_loss_price: "",
    take_profit_price: "",
  });
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function updateCandle(
    id: number,
    field: keyof Omit<CandleRow, "id">,
    value: string,
  ) {
    setCandles((current) =>
      current.map((candle) =>
        candle.id === id ? { ...candle, [field]: value } : candle,
      ),
    );
  }

  function addCandle() {
    setCandles((current) => [...current, emptyCandle(nextCandleId)]);
    setNextCandleId((current) => current + 1);
  }

  function removeCandle(id: number) {
    setCandles((current) => current.filter((candle) => candle.id !== id));
  }

  function updateTrade(field: keyof TradeFields, value: string) {
    setTrade((current) => ({ ...current, [field]: value }));
  }

  function handleCsvSelection(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) {
      return;
    }

    setCandleSource("csv");
    setCsvImport(null);
    setCsvImportStatus(`Validating ${file.name}…`);
    setError(null);
    setResult(null);
    void csvImportController.replace(file, (current, reading) => {
      setCsvImport(current);
      setIsReadingCsv(reading);
      if (reading) {
        setCsvImportStatus(`Validating ${file.name}…`);
      } else if (current?.result?.valid) {
        setCsvImportStatus(
          `${current.filename} validated: ${current.result.candles.length} candles ready.`,
        );
      } else {
        setCsvImportStatus(`${file.name} could not be imported.`);
      }
    });
  }

  function resetCsvImport() {
    csvImportController.reset((current, reading) => {
      setCsvImport(current);
      setIsReadingCsv(reading);
      setCsvImportStatus("");
    });
    setCandleSource("manual");
    setError(null);
    setResult(null);
  }

  function changeCandleSource(source: CandleSource) {
    setCandleSource(source);
    setError(null);
    setResult(null);
  }

  async function submitAnalysis(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    let tradeRequest: ProposedTradeRequest;
    let manualRequests: AnalysisCandleRequest[] = [];
    try {
      if (candleSource === "manual") {
        if (candles.length < 5) {
          throw new Error("Enter at least five candles to run an analysis.");
        }
        manualRequests = manualCandleRequests(candles);
      }

      tradeRequest = {};
      if (trade.direction !== "") {
        tradeRequest.direction = trade.direction;
      }
      for (const field of [
        "entry_price",
        "stop_loss_price",
        "take_profit_price",
      ] as const) {
        if (trade[field].trim() !== "") {
          tradeRequest[field] = numericInput(trade[field], field);
        }
      }
    } catch (validationError) {
      setError(
        validationError instanceof Error
          ? validationError.message
          : "Check the entered candle and trade values.",
      );
      return;
    }

    const currentImport = csvImportController.current;
    const importedCandles =
      currentImport?.result?.valid === true
        ? currentImport.result.candles
        : null;
    if (candleSource === "csv" && isReadingCsv) {
      setError("Wait for CSV validation to finish before running analysis.");
      return;
    }

    setIsSubmitting(true);
    try {
      const analysis = await analyzeSelectedCandles(
        candleSource,
        manualRequests,
        importedCandles,
        tradeRequest,
      );
      setResult(analysis);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The analysis request could not be completed.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="analysis-workspace" aria-labelledby="analysis-title">
      <div className="section-heading">
        <p className="eyebrow">Deterministic analysis</p>
        <h2 id="analysis-title">Analyze candles and a proposed trade</h2>
        <p className="section-intro">
          Enter timestamped candle data and optional trade values. Candle
          timestamps must be chronological; the service validates market data
          and trade geometry.
        </p>
      </div>

      <form className="analysis-form" onSubmit={submitAnalysis}>
        <fieldset className="source-selector">
          <legend>Candle data source</legend>
          <label>
            <input
              checked={candleSource === "manual"}
              disabled={isSubmitting}
              name="candle-source"
              onChange={() => changeCandleSource("manual")}
              type="radio"
              value="manual"
            />
            <span>Manual entry</span>
          </label>
          <label>
            <input
              checked={candleSource === "csv"}
              disabled={isSubmitting}
              name="candle-source"
              onChange={() => changeCandleSource("csv")}
              type="radio"
              value="csv"
            />
            <span>Import CSV</span>
          </label>
        </fieldset>

        {candleSource === "manual" ? (
          <section aria-labelledby="manual-candles-heading">
            <div className="form-section-heading">
              <h3 id="manual-candles-heading">Manual candles</h3>
              <button
                className="secondary-button"
                disabled={isSubmitting}
                onClick={addCandle}
                type="button"
              >
                Add candle
              </button>
            </div>

            <div className="candle-list">
              {candles.map((candle, index) => (
                <fieldset className="candle-row" key={candle.id}>
                  <legend>Candle {index + 1}</legend>
                  <div className="candle-fields">
                    {candleFields.map(([field, label]) => (
                      <label
                        className={field === "timestamp" ? "field-wide" : ""}
                        key={field}
                      >
                        <span>{label}</span>
                        <input
                          autoComplete="off"
                          name={`candle-${candle.id}-${field}`}
                          onChange={(event) =>
                            updateCandle(candle.id, field, event.target.value)
                          }
                          required
                          step={field === "timestamp" ? undefined : "any"}
                          type={
                            field === "timestamp" ? "datetime-local" : "number"
                          }
                          value={candle[field]}
                        />
                      </label>
                    ))}
                  </div>
                  <button
                    aria-label={`Remove candle ${index + 1}`}
                    className="remove-button"
                    disabled={isSubmitting}
                    onClick={() => removeCandle(candle.id)}
                    type="button"
                  >
                    Remove
                  </button>
                </fieldset>
              ))}
            </div>
          </section>
        ) : (
          <section className="csv-import" aria-labelledby="csv-import-heading">
            <h3 id="csv-import-heading">Import candle CSV</h3>
            <p className="field-hint">
              Choose a CSV with timestamp, open, high, low, close, and volume
              columns. Maximum 2 MiB and 5,000 candles.
            </p>
            <label className="csv-file-label" htmlFor="candle-csv-file">
              CSV file
            </label>
            <input
              accept=".csv,text/csv"
              disabled={isSubmitting}
              id="candle-csv-file"
              onChange={handleCsvSelection}
              type="file"
            />
            {csvImport && (
              <button
                className="secondary-button"
                disabled={isSubmitting}
                onClick={resetCsvImport}
                type="button"
              >
                Remove CSV and use manual entry
              </button>
            )}
            {isReadingCsv && (
              <p className="loading-message">
                {csvImportStatus}
              </p>
            )}
            <p className="sr-only" role="status" aria-live="polite">
              {csvImportStatus}
            </p>
            {csvImport?.error && (
              <p className="form-error" role="alert">
                {csvImport.error}
              </p>
            )}
            {csvImport?.result && !csvImport.result.valid && (
              <div className="csv-errors" role="alert">
                <p>
                  {csvImport.filename} has validation errors. Correct the CSV
                  and import it again.
                </p>
                <ul className="result-list">
                  {csvImport.result.errors.map((item, index) => (
                    <li key={`${item.line}-${item.column}-${index}`}>
                      Line {item.line}
                      {formatCsvColumn(item.column)}: {item.message}
                    </li>
                  ))}
                </ul>
                {csvImport.result.omittedErrorCount > 0 && (
                  <p>
                    {csvImport.result.omittedErrorCount} additional errors not
                    shown.
                  </p>
                )}
              </div>
            )}
            {csvImport?.result?.valid && (
              <div className="csv-preview">
                <h4>CSV preview</h4>
                <dl className="csv-summary">
                  <div>
                    <dt>File</dt>
                    <dd>{csvImport.filename}</dd>
                  </div>
                  <div>
                    <dt>Candles</dt>
                    <dd>{csvImport.result.candles.length}</dd>
                  </div>
                  <div>
                    <dt>First timestamp</dt>
                    <dd>{csvImport.result.candles[0].timestamp}</dd>
                  </div>
                  <div>
                    <dt>Last timestamp</dt>
                    <dd>
                      {
                        csvImport.result.candles[
                          csvImport.result.candles.length - 1
                        ].timestamp
                      }
                    </dd>
                  </div>
                </dl>
                <div className="csv-table-scroll">
                  <table>
                    <caption>
                      First{" "}
                      {Math.min(5, csvImport.result.candles.length)} candles
                      from {csvImport.filename}
                    </caption>
                    <thead>
                      <tr>
                        {CSV_COLUMNS.map((column) => (
                          <th key={column} scope="col">
                            {column}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {csvImport.result.candles.slice(0, 5).map((item, index) => (
                        <tr key={`${item.timestamp}-${index}`}>
                          {CSV_COLUMNS.map((column) => (
                            <td key={column}>{item[column]}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        )}

        <fieldset className="trade-section">
          <legend>Proposed trade</legend>
          <p className="field-hint">
            Leave a value blank to let the API report its trade-validation
            error.
          </p>
          <div className="trade-fields">
            <label>
              <span>Direction</span>
              <select
                name="direction"
                onChange={(event) =>
                  updateTrade("direction", event.target.value)
                }
                value={trade.direction}
              >
                <option value="">Not provided</option>
                <option value="long">Long</option>
                <option value="short">Short</option>
              </select>
            </label>
            {(
              [
                ["entry_price", "Entry price"],
                ["stop_loss_price", "Stop-loss price"],
                ["take_profit_price", "Take-profit price"],
              ] as const
            ).map(([field, label]) => (
              <label key={field}>
                <span>{label}</span>
                <input
                  name={field}
                  onChange={(event) =>
                    updateTrade(field, event.target.value)
                  }
                  step="any"
                  type="number"
                  value={trade[field]}
                />
              </label>
            ))}
          </div>
        </fieldset>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <button
          className="primary-button"
          disabled={isSubmitting}
          type="submit"
        >
          {isSubmitting ? "Analyzing…" : "Run analysis"}
        </button>
      </form>

      {isSubmitting && (
        <p className="loading-message" role="status">
          Analysis is running…
        </p>
      )}

      {result && (
        <div className="analysis-results" aria-live="polite">
          <section className="result-card" aria-labelledby="structure-title">
            <h3 id="structure-title">Market structure</h3>
            <p>
              <strong>Trend:</strong> {result.market_structure.trend}
            </p>
            <h4>Swings</h4>
            {result.market_structure.swings.length === 0 ? (
              <p className="empty-result">No swings detected.</p>
            ) : (
              <ul className="result-list">
                {result.market_structure.swings.map((swing, index) => (
                  <li key={`${swing.kind}-${swing.index}-${index}`}>
                    <strong>
                      {swing.kind} {swing.label ? `(${swing.label})` : ""}
                    </strong>
                    {" — "}
                    index {swing.index}, price {swing.price}; confirmed at
                    index {swing.confirmed_at_index} (
                    {formatTimestamp(swing.confirmed_at)})
                  </li>
                ))}
              </ul>
            )}
            <h4>Events</h4>
            {result.market_structure.events.length === 0 ? (
              <p className="empty-result">No structure events.</p>
            ) : (
              <ul className="result-list">
                {result.market_structure.events.map((event, index) => (
                  <li key={`${event.kind}-${event.index}-${index}`}>
                    <strong>{event.kind}</strong>
                    {event.direction ? ` — ${event.direction}` : ""}
                    {" — "}index {event.index}; level{" "}
                    {event.level_price ?? "Not available"}; level index{" "}
                    {event.level_index ?? "Not available"}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="result-card" aria-labelledby="sweeps-title">
            <h3 id="sweeps-title">Liquidity sweeps</h3>
            {result.liquidity_sweeps.length === 0 ? (
              <p className="empty-result">No liquidity sweeps detected.</p>
            ) : (
              <ul className="result-list">
                {result.liquidity_sweeps.map((sweep, index) => (
                  <li key={`${sweep.index}-${sweep.swing_index}-${index}`}>
                    <strong>{sweep.direction} sweep</strong>
                    {" — "}candle {sweep.index} at{" "}
                    {formatTimestamp(sweep.timestamp)}; {sweep.swing_kind} swing
                    {` ${sweep.swing_index}`} at {sweep.swing_price}; penetration{" "}
                    {sweep.penetration_price}; rejection close{" "}
                    {sweep.rejection_close}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="result-card" aria-labelledby="validation-title">
            <h3 id="validation-title">Proposed trade validation</h3>
            <p>
              <strong>Status:</strong>{" "}
              {result.trade_validation.is_valid ? "Valid" : "Invalid"}
            </p>
            <dl className="metric-list">
              <div>
                <dt>Risk distance</dt>
                <dd>{displayMetric(result.trade_validation.risk_distance)}</dd>
              </div>
              <div>
                <dt>Reward distance</dt>
                <dd>
                  {displayMetric(result.trade_validation.reward_distance)}
                </dd>
              </div>
              <div>
                <dt>Reward-to-risk ratio</dt>
                <dd>
                  {displayMetric(
                    result.trade_validation.reward_to_risk_ratio,
                  )}
                </dd>
              </div>
            </dl>
            <h4>Validation errors</h4>
            {result.trade_validation.errors.length === 0 ? (
              <p className="empty-result">No validation errors.</p>
            ) : (
              <ul className="result-list">
                {result.trade_validation.errors.map((item, index) => (
                  <li key={`${item.field}-${item.code}-${index}`}>
                    {item.field}: {item.code}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <p className="disclaimer">
            This validates the submitted data only. It is not financial advice
            or a recommendation, and no orders are placed.
          </p>
        </div>
      )}
    </section>
  );
}
