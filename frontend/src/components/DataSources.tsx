import type { DataSource } from "../types/api";

interface Props {
  sources: DataSource[];
}

const STATUS_BADGE: Record<string, { cls: string; label: string }> = {
  active: { cls: "badge-green", label: "Active" },
  configured: { cls: "badge-green", label: "Configured" },
  no_api_key: { cls: "badge-yellow", label: "No API Key" },
  not_configured: { cls: "badge-red", label: "Not Configured" },
};

export function DataSources({ sources }: Props) {
  return (
    <div className="grid grid-2">
      {sources.map((src) => {
        const status = STATUS_BADGE[src.status] || {
          cls: "badge-blue",
          label: src.status,
        };
        return (
          <div key={src.name} className="card">
            <div className="card-header">
              <div>
                <span className="card-title">{src.name}</span>
                <span className="text-muted" style={{ marginLeft: 8, fontSize: "0.75rem" }}>
                  {src.type}
                </span>
              </div>
              <span className={`badge ${status.cls}`}>{status.label}</span>
            </div>
            <div style={{ marginBottom: 8 }}>
              {src.provides.map((p) => (
                <span
                  key={p}
                  style={{
                    display: "inline-block",
                    background: "var(--bg-secondary)",
                    padding: "2px 8px",
                    borderRadius: 4,
                    fontSize: "0.75rem",
                    marginRight: 4,
                    marginBottom: 4,
                    color: "var(--text-secondary)",
                  }}
                >
                  {p}
                </span>
              ))}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Cost: {src.cost}
              {src.key_env && (
                <span style={{ marginLeft: 8 }}>
                  Env: <code style={{ color: "var(--cyan)" }}>{src.key_env}</code>
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
