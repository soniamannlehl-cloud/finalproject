import type { StructuredThesis, ThesisVersion } from "@/lib/types";

const VALUATION_LABELS: Record<string, string> = {
  cheap: "Cheap",
  fair: "Fair",
  expensive: "Expensive",
  insufficient_data: "Insufficient data",
};

function FrameworkView({ fw }: { fw: StructuredThesis }) {
  const valLabel = VALUATION_LABELS[fw.valuation_opinion] || fw.valuation_opinion;
  const rec = fw.recommendation.replace(/_/g, " ");

  return (
    <div className="space-y-5 text-sm">
      <section>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Core question ({fw.horizon || "3-5 years"})
        </h3>
        <p className="font-medium text-slate-900">{fw.core_question}</p>
      </section>

      <section>
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Primary investment thesis
        </h3>
        <p className="leading-relaxed text-slate-800">{fw.primary_thesis}</p>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Supporting drivers
        </h3>
        <ul className="list-inside list-disc space-y-1 text-slate-700">
          {fw.supporting_drivers.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Key risks</h3>
        <ul className="list-inside list-disc space-y-1 text-slate-700">
          {fw.key_risks.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-emerald-700">
            Positive catalysts
          </h3>
          <ul className="list-inside list-disc space-y-1 text-slate-700">
            {fw.positive_catalysts.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-rose-700">
            Negative catalysts
          </h3>
          <ul className="list-inside list-disc space-y-1 text-slate-700">
            {fw.negative_catalysts.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Valuation opinion
          </h3>
          <p className="font-semibold capitalize text-slate-900">{valLabel}</p>
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Confidence</h3>
          <p className="font-semibold text-slate-900">{Math.round(fw.confidence * 100)}%</p>
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Recommendation
          </h3>
          <p className="font-semibold uppercase text-slate-900">{rec}</p>
        </div>
      </section>

      {fw.missing_evidence.length > 0 &&
        !fw.missing_evidence[0]?.startsWith("None —") && (
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-700">
              Missing evidence
            </h3>
            <ul className="list-inside list-disc space-y-1 text-slate-600">
              {fw.missing_evidence.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          </section>
        )}
    </div>
  );
}

export function ThesisPanel({
  current,
  history,
  framework,
}: {
  current: ThesisVersion | null;
  history: ThesisVersion[];
  framework?: StructuredThesis | null;
}) {
  const fw = framework || current?.framework;

  if (!current && !fw) {
    return (
      <section className="card">
        <h2 className="section-title">Investment thesis</h2>
        <p className="text-sm text-slate-500">Thesis will form as evidence arrives.</p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 className="section-title">Investment thesis</h2>
      {current && (
        <div className="mb-4 flex flex-wrap gap-3 text-sm">
          <span className="rounded-full bg-slate-100 px-3 py-1 font-medium capitalize">{current.stance}</span>
          <span className="rounded-full bg-slate-100 px-3 py-1">
            Confidence {Math.round(current.confidence * 100)}%
          </span>
          <span className="rounded-full bg-slate-100 px-3 py-1">Version {current.version}</span>
        </div>
      )}

      {fw ? (
        <FrameworkView fw={fw} />
      ) : (
        <p className="mb-4 leading-relaxed text-slate-800">{current?.statement}</p>
      )}

      {current?.change_reason && (
        <p className="mt-4 text-xs text-slate-500">Latest change: {current.change_reason}</p>
      )}
      {history.length > 1 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-medium text-brand">
            View thesis history ({history.length} versions)
          </summary>
          <ol className="mt-3 space-y-2 border-l-2 border-slate-200 pl-4">
            {history.map((v) => (
              <li key={v.version} className="text-slate-600">
                <span className="font-medium text-slate-800">v{v.version}</span> —{" "}
                {(v.framework?.primary_thesis || v.statement).slice(0, 120)}…
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
