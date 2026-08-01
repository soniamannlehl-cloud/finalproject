import { reportHtmlUrl, reportPdfUrl } from "@/lib/api";
import type { Recommendation } from "@/lib/types";
import { cleanCommitteeText, formatAction } from "@/lib/format";

export function ReportPanel({ runId, reportId }: { runId: string; reportId?: string }) {
  if (!reportId) return null;

  const htmlUrl = reportHtmlUrl(runId);
  const pdfUrl = reportPdfUrl(runId);

  return (
    <section className="card border-emerald-200 bg-emerald-50/50">
      <h2 className="section-title text-emerald-900">Final investment report</h2>
      <p className="mb-4 text-sm text-emerald-800">
        Your research report is ready. Every claim is backed by cited evidence from the repository.
      </p>
      <div className="flex flex-wrap gap-3">
        <a href={htmlUrl} target="_blank" rel="noopener noreferrer" className="btn-primary">
          View HTML report
        </a>
        <a href={pdfUrl} className="btn-secondary bg-white">
          Download PDF
        </a>
      </div>
    </section>
  );
}

export function RecommendationSummary({ recommendation }: { recommendation?: Recommendation | null }) {
  if (!recommendation?.action) return null;

  return (
    <section className="card">
      <h2 className="section-title">Committee recommendation</h2>
      <p className="text-2xl font-bold uppercase text-slate-900">{formatAction(recommendation.action)}</p>
      {recommendation.was_downgraded && (
        <p className="mt-2 rounded-lg bg-amber-50 p-2 text-sm text-amber-800">
          Downgraded by safety gate: {recommendation.gate_reasons?.join("; ")}
        </p>
      )}
      {recommendation.cio_rationale && (
        <p className="mt-3 text-sm leading-relaxed text-slate-600">
          {cleanCommitteeText(recommendation.cio_rationale)}
        </p>
      )}
    </section>
  );
}
