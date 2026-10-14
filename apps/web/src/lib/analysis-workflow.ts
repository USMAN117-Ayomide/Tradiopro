import {
  analyzeMarket,
  type AnalysisCandleRequest,
  type AnalysisResponse,
  type ProposedTradeRequest,
} from "@/lib/analysis-api";
import {
  CSV_MAX_FILE_BYTES,
  parseCsvCandles,
  selectAnalysisCandles,
  type CandleSource,
  type CsvImportResult,
} from "@/lib/csv-candles";
import {
  formatCandleValidationIssue,
  validateCandleSeries,
} from "@/lib/candle-validation";

export interface CsvFileLike {
  name: string;
  size: number;
  text(): Promise<string>;
}

export interface CsvFileImport {
  filename: string;
  result: CsvImportResult | null;
  error: string | null;
}

export async function readCsvFile(file: CsvFileLike): Promise<CsvFileImport> {
  try {
    if (file.size > CSV_MAX_FILE_BYTES) {
      return {
        filename: file.name,
        result: null,
        error: "CSV file exceeds the 2 MiB limit.",
      };
    }

    return {
      filename: file.name,
      result: parseCsvCandles(await file.text()),
      error: null,
    };
  } catch {
    return {
      filename: file.name,
      result: null,
      error: "The selected CSV could not be read or validated. Try another file.",
    };
  }
}

export class CsvImportController {
  private revision = 0;
  private currentImport: CsvFileImport | null = null;

  get current(): CsvFileImport | null {
    return this.currentImport;
  }

  async replace(
    file: CsvFileLike,
    onChange: (current: CsvFileImport | null, isReading: boolean) => void,
  ): Promise<void> {
    const revision = ++this.revision;
    this.currentImport = null;
    onChange(null, true);

    const imported = await readCsvFile(file);
    if (revision !== this.revision) {
      return;
    }

    this.currentImport = imported;
    onChange(imported, false);
  }

  reset(
    onChange: (current: CsvFileImport | null, isReading: boolean) => void,
  ): void {
    this.revision += 1;
    this.currentImport = null;
    onChange(null, false);
  }
}

export async function analyzeSelectedCandles(
  source: CandleSource,
  manualCandles: AnalysisCandleRequest[],
  importedCandles: AnalysisCandleRequest[] | null,
  trade: ProposedTradeRequest,
): Promise<AnalysisResponse> {
  const candles = selectAnalysisCandles(
    source,
    manualCandles,
    importedCandles,
  );
  const issues = validateCandleSeries(candles);
  if (issues.length > 0) {
    throw new Error(formatCandleValidationIssue(issues[0]));
  }
  return analyzeMarket({ candles, trade });
}
