import type { Position } from "../types/api";

interface Props {
  positions: Position[];
  onCloseAll?: () => void;
}

export function PositionsTable({ positions, onCloseAll }: Props) {
  if (!positions.length) {
    return (
      <div className="empty-state">
        <h3>No Open Positions</h3>
        <p>Execute trades from the Scanner to open positions</p>
      </div>
    );
  }

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);

  return (
    <div>
      <div className="card-header">
        <div>
          <span className="card-title">Open Positions</span>
          <span
            style={{ marginLeft: 12 }}
            className={totalPnl >= 0 ? "text-green" : "text-red"}
          >
            {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)} total P&L
          </span>
        </div>
        {onCloseAll && (
          <button className="btn btn-danger" onClick={onCloseAll}>
            Close All
          </button>
        )}
      </div>
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Strategy</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Current</th>
              <th>P&L</th>
              <th>P&L %</th>
              <th>Allocation</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => (
              <tr key={pos.symbol}>
                <td style={{ fontWeight: 700, color: "var(--cyan)" }}>
                  {pos.symbol}
                </td>
                <td>
                  {pos.strategy && (
                    <span className="badge badge-blue">
                      {pos.strategy.replace(/_/g, " ")}
                    </span>
                  )}
                </td>
                <td>{pos.quantity}</td>
                <td>${pos.entry_price.toFixed(2)}</td>
                <td>${pos.current_price.toFixed(2)}</td>
                <td className={pos.pnl >= 0 ? "text-green" : "text-red"}>
                  {pos.pnl >= 0 ? "+" : ""}${pos.pnl.toFixed(2)}
                </td>
                <td className={pos.pnl_pct >= 0 ? "text-green" : "text-red"}>
                  {pos.pnl_pct >= 0 ? "+" : ""}
                  {pos.pnl_pct.toFixed(2)}%
                </td>
                <td>{pos.allocation_pct.toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
