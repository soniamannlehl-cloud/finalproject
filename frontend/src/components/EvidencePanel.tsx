import type { EvidenceItem } from "@/lib/types";

export function EvidencePanel({
  evidence,
  byCapability,
}: {
  evidence: EvidenceItem[];
  byCapability?: Record<string, { count: number }>;
}) {
  if (!evidence.length) {
    return (
      <section className="card">
        <h2 className="section-title">Evidence</h2>
        <p className="text-sm text-slate-500">No evidence gathered yet.</p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 className="section-title">Evidence repository ({evidence.length})</h2>
      {byCapability && (
        <div className="mb-4 flex flex-wrap gap-2">
          {Object.entries(byCapability).map(([cap, info]) => (
            <span key={cap} className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">
              {cap.replace(/\./g, " · ")}: {info.count}
            </span>
          ))}
        </div>
      )}
      <ul className="max-h-96 space-y-2 overflow-y-auto">
        {evidence.map((ev) => (
          <li key={ev.evidence_id} className="rounded-lg border border-slate-100 p-3 text-sm">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="rounded bg-brand/10 px-2 py-0.5 text-xs font-medium text-brand">
                {ev.capability}
              </span>
              {ev.provider_degraded && (
                <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">degraded</span>
              )}
              <span className="text-xs text-slate-400">{(ev.confidence ?? 0).toFixed(2)} conf.</span>
            </div>
            <p className="text-slate-700">{ev.summary || ev.citation || "No summary"}</p>
            <p className="mt-1 text-xs text-slate-400">{ev.source_name}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
