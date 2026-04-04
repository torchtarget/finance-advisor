import type { Portfolio } from "../types/api";

interface Props {
  portfolio: Portfolio | null;
}

export function PortfolioStats({ portfolio }: Props) {
  if (!portfolio) {
    return (
      <div className="grid grid-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="card stat">
            <div className="stat-value text-muted">--</div>
            <div className="stat-label">Loading</div>
          </div>
        ))}
      </div>
    );
  }

  const returnColor =
    portfolio.total_return_pct >= 0 ? "text-green" : "text-red";

  return (
    <div className="grid grid-4">
      <div className="card stat">
        <div className="stat-value">${portfolio.total_value.toLocaleString()}</div>
        <div className="stat-label">Total Value</div>
      </div>
      <div className="card stat">
        <div className={`stat-value ${returnColor}`}>
          {portfolio.total_return_pct >= 0 ? "+" : ""}
          {portfolio.total_return_pct.toFixed(1)}%
        </div>
        <div className="stat-label">Weekly Return</div>
      </div>
      <div className="card stat">
        <div className="stat-value">${portfolio.cash.toLocaleString()}</div>
        <div className="stat-label">Cash</div>
      </div>
      <div className="card stat">
        <div className="stat-value">{portfolio.positions.length}</div>
        <div className="stat-label">Open Positions</div>
      </div>
    </div>
  );
}
