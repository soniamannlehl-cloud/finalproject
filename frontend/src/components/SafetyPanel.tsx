export function SafetyPanel({
  safety,
}: {
  safety: {
    evidence_score?: number;
    is_blocking?: boolean;
    semantic_verified?: boolean;
    findings?: Array<{ check_name: string; severity: string; message: string }>;
    coverage?: { satisfied_capabilities?: string[]; required_capabilities?: string[] };
  } | null;
}) {
  if (!safety || safety.evidence_score === undefined) {
    return (
      <section className="card">
        <h2 className="section-title">Safety pipeline</h2>
        <p className="text-sm text-slate-500">Safety checks run after research completes.</p>
      </section>
    );
  }

  const findings = safety.findings || [];
  const blocking = findings.filter((f) => f.severity === "blocking");

  return (
    <section className="card">
      <h2 className="section-title">Safety pipeline</h2>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <div className="metric">
          <p className="metric-label">Evidence score</p>
          <p className="metric-value">{safety.evidence_score?.toFixed(2)}</p>
        </div>
        <div className="metric">
          <p className="metric-label">Semantic verified</p>
          <p className="metric-value">{safety.semantic_verified ? "Yes" : "Partial"}</p>
        </div>
        <div className="metric">
          <p className="metric-label">Blocking issues</p>
          <p className="metric-value">{blocking.length}</p>
        </div>
      </div>
      {findings.length > 0 && (
        <ul className="max-h-48 space-y-1 overflow-y-auto text-sm">
          {findings.slice(0, 12).map((f, i) => (
            <li key={i} className="flex gap-2 text-slate-600">
              <span
                className={`shrink-0 rounded px-1.5 text-xs font-medium ${
                  f.severity === "blocking"
                    ? "bg-red-100 text-red-800"
                    : f.severity === "warning"
                      ? "bg-amber-100 text-amber-800"
                      : "bg-slate-100 text-slate-600"
                }`}
              >
                {f.severity}
              </span>
              {f.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
