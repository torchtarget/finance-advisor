import type { Recommendation } from "../types/api";

interface Props {
  recommendations: Recommendation[];
  onSymbolClick?: (symbol: string) => void;
}

const STRATEGY_COLORS: Record<string, string> = {
  momentum_breakout: "badge-blue",
  mean_reversion_oversold: "badge-green",
  squeeze_setup: "badge-purple",
  earnings_gap: "badge-yellow",
  high_short_interest: "badge-red",
  volume_spike: "badge-blue",
};

export function RecommendationsTable({ recommendations, onSymbolClick }: Props) {
  if (!recommendations.length) {
    return (
      <div className="empty-state">
        <h3>No Signals</h3>
        <p>Run a scan to find weekly trade opportunities</p>
      </div>
    );
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Symbol</th>
            <th>Strategy</th>
            <th>Confidence</th>
            <th>Entry</th>
            <th>Target</th>
            <th>Exp. Return</th>
            <th>Allocation</th>
            <th>Qty</th>
            <th>Cost</th>
          </tr>
        </thead>
        <tbody>
          {recommendations.map((rec) => {
            const confidenceColor =
              rec.confidence >= 0.7
                ? "var(--green)"
                : rec.confidence >= 0.5
                  ? "var(--yellow)"
                  : "var(--red)";

            return (
              <tr key={`${rec.symbol}-${rec.rank}`}>
                <td style={{ fontWeight: 700, color: "var(--text-muted)" }}>
                  {rec.rank}
                </td>
                <td>
                  <button
                    onClick={() => onSymbolClick?.(rec.symbol)}
                    style={{
                      background: "none",
                      border: "none",
                      color: "var(--cyan)",
                      fontWeight: 700,
                      cursor: "pointer",
                      fontSize: "0.875rem",
                    }}
                  >
                    {rec.symbol}
                  </button>
                </td>
                <td>
                  <span
                    className={`badge ${STRATEGY_COLORS[rec.strategy] || "badge-blue"}`}
                  >
                    {rec.strategy.replace(/_/g, " ")}
                  </span>
                </td>
                <td>
                  <div className="confidence-bar">
                    <div
                      className="confidence-fill"
                      style={{
                        width: `${rec.confidence * 100}%`,
                        background: confidenceColor,
                      }}
                    />
                  </div>
                  <span style={{ fontSize: "0.8rem" }}>
                    {(rec.confidence * 100).toFixed(0)}%
                  </span>
                </td>
                <td>${rec.entry_price.toFixed(2)}</td>
                <td>
                  {rec.target_price
                    ? `$${rec.target_price.toFixed(2)}`
                    : "—"}
                </td>
                <td>
                  <span
                    className={
                      (rec.expected_return_pct ?? 0) >= 0
                        ? "text-green"
                        : "text-red"
                    }
                  >
                    {rec.expected_return_pct
                      ? `+${rec.expected_return_pct.toFixed(1)}%`
                      : "—"}
                  </span>
                </td>
                <td style={{ fontWeight: 600, color: "var(--yellow)" }}>
                  {rec.allocation_pct.toFixed(0)}%
                </td>
                <td>{rec.quantity}</td>
                <td>${rec.cost.toLocaleString()}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* Rationales */}
      <div style={{ marginTop: 16 }}>
        {recommendations.map((rec) => (
          <div
            key={`rationale-${rec.symbol}`}
            className="rationale"
            style={{ marginBottom: 8 }}
          >
            <span style={{ color: "var(--cyan)", fontWeight: 600 }}>
              {rec.symbol}
            </span>
            : {rec.rationale}
            {rec.max_loss_pct && (
              <span className="text-red">
                {" "}
                (Max loss: {rec.max_loss_pct.toFixed(0)}% of capital)
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
