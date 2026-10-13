import Link from "next/link";
import AnalysisForm from "@/components/analysis-form";

export default function Home() {
  return (
    <main className="workspace">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="Tradiopro home">
          <span className="brand-mark" aria-hidden="true">
            T
          </span>
          Tradiopro
        </Link>
        <span className="environment-label">Analysis workspace</span>
      </header>

      <section className="welcome" aria-labelledby="welcome-title">
        <p className="eyebrow">Market analysis workspace</p>
        <h1 id="welcome-title">Build your edge with a clearer view.</h1>
        <p className="intro">
          A home for structured forex and cryptocurrency analysis, with risk
          validation at its core.
        </p>

        <div className="status-card" role="status">
          <span className="status-indicator" aria-hidden="true" />
          <div>
            <strong>Foundation is ready</strong>
            <p>
              Enter candle data below to run the deterministic analysis API.
            </p>
          </div>
        </div>

        <p className="disclaimer">
          Tradiopro is an analysis tool, not financial advice. No orders are
          placed by this application.
        </p>
      </section>
      <AnalysisForm />
    </main>
  );
}
