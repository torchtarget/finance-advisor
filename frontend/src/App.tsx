import { useState, useEffect, useCallback } from "react";
import { useApi } from "./hooks/useApi";
import { PortfolioStats } from "./components/PortfolioStats";
import { RecommendationsTable } from "./components/RecommendationsTable";
import { PositionsTable } from "./components/PositionsTable";
import { PriceChart } from "./components/PriceChart";
import { DataSources } from "./components/DataSources";
import type {
  Recommendation,
  Portfolio,
  Quote,
  DataSource,
  Strategy,
  NewsArticle,
} from "./types/api";
import "./index.css";

type Tab = "scanner" | "portfolio" | "detail" | "sources";

function App() {
  const { get, post, loading, error } = useApi();

  const [tab, setTab] = useState<Tab>("scanner");
  const [capital, setCapital] = useState(1000);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [dataSources, setDataSources] = useState<DataSource[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [scanStats, setScanStats] = useState<{
    total_candidates: number;
    total_signals: number;
    scanned_at: string;
  } | null>(null);

  // Load initial data
  useEffect(() => {
    get<{ sources: DataSource[] }>("/data-sources").then(
      (r) => r && setDataSources(r.sources)
    );
    get<{ strategies: Strategy[] }>("/strategies").then(
      (r) => r && setStrategies(r.strategies)
    );
    get<Portfolio>("/portfolio").then((r) => r && setPortfolio(r));
  }, [get]);

  const runScan = useCallback(async () => {
    const result = await post<{
      recommendations: Recommendation[];
      total_candidates: number;
      total_signals: number;
      scanned_at: string;
    }>("/scan", { capital });
    if (result) {
      setRecommendations(result.recommendations);
      setScanStats({
        total_candidates: result.total_candidates,
        total_signals: result.total_signals,
        scanned_at: result.scanned_at,
      });
    }
  }, [post, capital]);

  const viewSymbol = useCallback(
    async (symbol: string) => {
      setSelectedSymbol(symbol);
      setTab("detail");
      const [q, n] = await Promise.all([
        get<Quote>(`/quote/${symbol}`),
        get<{ articles: NewsArticle[] }>(`/news/${symbol}`),
      ]);
      if (q) setQuote(q);
      if (n) setNews(n.articles);
    },
    [get]
  );

  const trackPaperTrades = useCallback(async () => {
    await post("/paper/buy", { capital });
    const p = await get<Portfolio>("/portfolio");
    if (p) setPortfolio(p);
    setTab("portfolio");
  }, [post, get, capital]);

  const closeAllPaper = useCallback(async () => {
    await post("/paper/close-all");
    const p = await get<Portfolio>("/portfolio");
    if (p) setPortfolio(p);
  }, [post, get]);

  return (
    <div className="app">
      {/* Header */}
      <div className="header">
        <div>
          <h1>Weekly Trading Advisor</h1>
          <div className="subtitle">
            High-risk speculative picks for DeGiro instruments
          </div>
        </div>
        <div className="header-actions">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label
              style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}
            >
              Capital: $
            </label>
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              style={{
                width: 80,
                padding: "6px 10px",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                color: "var(--text-primary)",
                fontSize: "0.875rem",
              }}
            />
          </div>
          <span className="mode-badge mode-paper">Paper Mode</span>
        </div>
      </div>

      {/* Warning */}
      <div className="warning-banner">
        <span style={{ fontSize: "1.1rem" }}>!</span>
        <span>
          HIGH RISK — This advisor targets maximum short-term returns. You can
          lose your entire ${capital.toLocaleString()}. Not financial advice.
        </span>
      </div>

      {/* Tabs */}
      <div className="tabs">
        <button
          className={`tab ${tab === "scanner" ? "active" : ""}`}
          onClick={() => setTab("scanner")}
        >
          Scanner
        </button>
        <button
          className={`tab ${tab === "portfolio" ? "active" : ""}`}
          onClick={() => setTab("portfolio")}
        >
          Portfolio
          {portfolio && portfolio.positions.length > 0 && (
            <span
              style={{
                background: "var(--accent)",
                borderRadius: "50%",
                width: 18,
                height: 18,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "0.65rem",
                fontWeight: 700,
              }}
            >
              {portfolio.positions.length}
            </span>
          )}
        </button>
        {selectedSymbol && (
          <button
            className={`tab ${tab === "detail" ? "active" : ""}`}
            onClick={() => setTab("detail")}
          >
            {selectedSymbol}
          </button>
        )}
        <button
          className={`tab ${tab === "sources" ? "active" : ""}`}
          onClick={() => setTab("sources")}
        >
          Data Sources
        </button>
      </div>

      {/* Error display */}
      {error && (
        <div
          className="card"
          style={{ borderColor: "var(--red)", color: "var(--red)" }}
        >
          Error: {error}
        </div>
      )}

      {/* Scanner Tab */}
      {tab === "scanner" && (
        <div>
          <div className="card">
            <div className="card-header">
              <div>
                <span className="card-title">Weekly Scan</span>
                {scanStats && (
                  <span
                    className="text-muted"
                    style={{ marginLeft: 12, fontSize: "0.8rem" }}
                  >
                    {scanStats.total_candidates} scanned |{" "}
                    {scanStats.total_signals} signals |{" "}
                    {new Date(scanStats.scanned_at).toLocaleTimeString()}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="btn btn-primary"
                  onClick={runScan}
                  disabled={loading}
                >
                  {loading ? (
                    <>
                      <span className="spinner" /> Scanning...
                    </>
                  ) : (
                    "Run Scan"
                  )}
                </button>
                {recommendations.length > 0 && (
                  <button
                    className="btn btn-outline"
                    onClick={trackPaperTrades}
                  >
                    Track as Paper Trades
                  </button>
                )}
              </div>
            </div>
            <RecommendationsTable
              recommendations={recommendations}
              onSymbolClick={viewSymbol}
            />
          </div>

          {/* Strategies info */}
          {strategies.length > 0 && (
            <div className="card">
              <div className="card-title" style={{ marginBottom: 12 }}>
                Active Strategies
              </div>
              <div className="grid grid-3">
                {strategies.map((s) => (
                  <div
                    key={s.name}
                    style={{
                      padding: 12,
                      background: "var(--bg-secondary)",
                      borderRadius: 8,
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: "0.85rem",
                        marginBottom: 4,
                        color: "var(--cyan)",
                      }}
                    >
                      {s.name.replace(/_/g, " ")}
                    </div>
                    <div
                      style={{
                        fontSize: "0.75rem",
                        color: "var(--text-secondary)",
                      }}
                    >
                      {s.description}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Portfolio Tab */}
      {tab === "portfolio" && (
        <div>
          <PortfolioStats portfolio={portfolio} />
          <div className="card" style={{ marginTop: 16 }}>
            <PositionsTable
              positions={portfolio?.positions || []}
              onCloseAll={
                portfolio && portfolio.positions.length > 0
                  ? closeAllPaper
                  : undefined
              }
            />
          </div>
        </div>
      )}

      {/* Symbol Detail Tab */}
      {tab === "detail" && selectedSymbol && (
        <div>
          <div className="card">
            <PriceChart
              data={quote?.price_history || []}
              symbol={selectedSymbol}
            />
          </div>

          {/* Indicators */}
          {quote && (
            <div className="card">
              <div className="card-title" style={{ marginBottom: 12 }}>
                Technical Indicators
              </div>
              <div className="grid grid-4">
                {Object.entries(quote.indicators).map(([key, value]) => (
                  <div key={key} className="stat">
                    <div className="stat-value" style={{ fontSize: "1.1rem" }}>
                      {typeof value === "boolean"
                        ? value
                          ? "Yes"
                          : "No"
                        : typeof value === "number"
                          ? value.toFixed(2)
                          : String(value)}
                    </div>
                    <div className="stat-label">
                      {key.replace(/_/g, " ")}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* News */}
          {news.length > 0 && (
            <div className="card">
              <div className="card-title" style={{ marginBottom: 12 }}>
                Recent News
              </div>
              {news.slice(0, 8).map((article, i) => (
                <div
                  key={i}
                  style={{
                    padding: "10px 0",
                    borderBottom:
                      i < 7 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <a
                    href={article.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: "var(--text-primary)",
                      textDecoration: "none",
                      fontSize: "0.875rem",
                      fontWeight: 500,
                    }}
                  >
                    {article.title}
                  </a>
                  <div
                    style={{
                      fontSize: "0.7rem",
                      color: "var(--text-muted)",
                      marginTop: 2,
                    }}
                  >
                    {article.publisher} |{" "}
                    {new Date(article.published).toLocaleDateString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Data Sources Tab */}
      {tab === "sources" && (
        <div>
          <div style={{ marginBottom: 16 }}>
            <h2 style={{ fontSize: "1.1rem", marginBottom: 8 }}>
              Data Sources
            </h2>
            <p className="text-muted" style={{ fontSize: "0.85rem" }}>
              All market data is sourced from free APIs. Add API keys to unlock
              additional sentiment and news data.
            </p>
          </div>
          <DataSources sources={dataSources} />
        </div>
      )}
    </div>
  );
}

export default App;
