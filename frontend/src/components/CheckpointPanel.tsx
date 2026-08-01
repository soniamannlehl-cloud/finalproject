"use client";

import { useState } from "react";
import type { Checkpoint, StructuredThesis } from "@/lib/types";
import { reportHtmlUrl, reportPdfUrl } from "@/lib/api";
import { cleanCommitteeText, formatAction, recommendationTone } from "@/lib/format";

interface Props {
  checkpoint: Checkpoint;
  onAction: (action: string, extras?: { ticker?: string; feedback?: string }) => void;
  loading: boolean;
  thesisStatement?: string;
  thesisFramework?: StructuredThesis | null;
  thesisConfidence?: number;
  safetyEvidenceScore?: number;
}

export function CheckpointPanel({ checkpoint, onAction, loading, thesisStatement, thesisFramework, thesisConfidence, safetyEvidenceScore }: Props) {
  const [feedback, setFeedback] = useState("");
  const [selectedTicker, setSelectedTicker] = useState("");

  if (checkpoint.type === "checkpoint_1_company_confirmation") {
    const match = checkpoint.top_match;
    return (
      <section className="overflow-hidden rounded-2xl border border-amber-200 bg-white shadow-md">
        <div className="border-b border-amber-100 bg-gradient-to-r from-amber-50 to-white px-6 py-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-700">
            Checkpoint 1 · Company validation
          </p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">Confirm this company</h2>
        </div>
        <div className="p-6">
          <p className="mb-4 text-slate-600">{checkpoint.prompt}</p>
          {match && (
            <div className="mb-5 rounded-xl bg-slate-50 p-5 ring-1 ring-slate-100">
              <p className="text-2xl font-bold text-slate-900">{match.name}</p>
              <p className="text-lg font-medium text-brand">{match.ticker}</p>
              {(match.sector || match.industry) && (
                <p className="mt-1 text-sm text-slate-500">
                  {[match.sector, match.industry].filter(Boolean).join(" · ")}
                </p>
              )}
            </div>
          )}
          {checkpoint.candidates && checkpoint.candidates.length > 1 && (
            <label className="mb-5 block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Or select alternate</span>
              <select
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5"
                value={selectedTicker}
                onChange={(e) => setSelectedTicker(e.target.value)}
              >
                <option value="">Use top match</option>
                {checkpoint.candidates.map((c) => (
                  <option key={c.ticker} value={c.ticker}>
                    {c.name} ({c.ticker})
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              disabled={loading}
              onClick={() => onAction("confirm", selectedTicker ? { ticker: selectedTicker } : undefined)}
              className="btn-primary"
            >
              {loading ? "Processing…" : "Confirm & start research"}
            </button>
            <button type="button" disabled={loading} onClick={() => onAction("reject")} className="btn-secondary">
              Wrong company
            </button>
          </div>
        </div>
      </section>
    );
  }

  if (checkpoint.type === "checkpoint_2_committee_review") {
    const rec = checkpoint.recommendation;
    const action = formatAction(rec?.action);
    const tone = recommendationTone(rec?.action);
    const runId = checkpoint.run_id;
    const isInsufficient = String(rec?.action || "").includes("insufficient");

    const summaryText = cleanCommitteeText(
      checkpoint.research_summary ||
        thesisFramework?.primary_thesis ||
        thesisStatement ||
        checkpoint.thesis_statement ||
        checkpoint.cio_rationale,
    );
    const thesisConf = checkpoint.thesis_confidence ?? thesisConfidence;
    const evidenceScore = checkpoint.evidence_score ?? rec?.evidence_score ?? safetyEvidenceScore;
    const coveragePct =
      checkpoint.coverage_ratio != null ? Math.round(checkpoint.coverage_ratio * 100) : null;

    return (
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-md">
        <div className="bg-slate-900 px-6 py-5 text-white">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
            Checkpoint 2 · Review research
          </p>
          <h2 className="mt-1 text-xl font-semibold">Research complete — review before finalizing</h2>
          {runId && (
            <div className="mt-4 flex flex-wrap gap-3">
              <a
                href={reportHtmlUrl(runId)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-900 transition hover:bg-slate-100"
              >
                Open full report
              </a>
              <a
                href={reportPdfUrl(runId)}
                className="inline-flex items-center rounded-lg border border-slate-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
              >
                Download PDF
              </a>
            </div>
          )}
        </div>

        <div className="space-y-6 p-6">
          {/* Research summary */}
          {summaryText && (
            <div className="rounded-xl bg-slate-50 p-5 ring-1 ring-slate-100">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Research summary
              </p>
              <p className="text-sm leading-relaxed text-slate-800">{summaryText}</p>
            </div>
          )}

          {/* Outcome + quality metrics */}
          <div className={`rounded-xl border-l-4 bg-white p-5 shadow-sm ring-1 ring-slate-100 ${tone.accent}`}>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Outcome</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <span className={`rounded-full px-3 py-1 text-sm font-bold uppercase ring-1 ${tone.badge}`}>
                {action}
              </span>
              {!isInsufficient && rec?.confidence != null && (
                <span className="text-sm text-slate-600">
                  Committee confidence {Math.round(rec.confidence * 100)}%
                </span>
              )}
            </div>
            {isInsufficient && (
              <p className="mt-3 text-sm text-slate-600">
                The safety pipeline could not verify enough research for a buy, sell, or hold call.
                Request more research to fill gaps, or approve to finalize the report as-is.
              </p>
            )}
            {isInsufficient && checkpoint.failed_capabilities && checkpoint.failed_capabilities.length > 0 && (
              <p className="mt-2 text-sm text-slate-500">
                Missing:{" "}
                {checkpoint.failed_capabilities
                  .map((c) => c.replace(/\./g, " · ").replace(/_/g, " "))
                  .join(", ")}
              </p>
            )}
            {rec?.was_downgraded && rec.gate_reasons && rec.gate_reasons.length > 0 && (
              <p className="mt-2 text-sm text-amber-800">{rec.gate_reasons.join(" · ")}</p>
            )}

            <dl className="mt-4 grid gap-4 sm:grid-cols-3">
              {thesisConf != null && (
                <div>
                  <dt className="text-xs text-slate-500">Thesis confidence</dt>
                  <dd className="text-lg font-semibold text-slate-900">
                    {Math.round(thesisConf * 100)}%
                    {checkpoint.thesis_stance && (
                      <span className="ml-1 text-sm font-normal capitalize text-slate-500">
                        ({checkpoint.thesis_stance})
                      </span>
                    )}
                  </dd>
                </div>
              )}
              {evidenceScore != null && (
                <div>
                  <dt className="text-xs text-slate-500">Evidence score</dt>
                  <dd className="text-lg font-semibold text-slate-900">{evidenceScore.toFixed(2)}</dd>
                </div>
              )}
              {coveragePct != null && (
                <div>
                  <dt className="text-xs text-slate-500">Research coverage</dt>
                  <dd className="text-lg font-semibold text-slate-900">{coveragePct}%</dd>
                </div>
              )}
            </dl>
          </div>

          {/* Actions */}
          <div className="rounded-xl border border-slate-200 p-5">
            <label className="block text-sm">
              <span className="mb-2 block font-medium text-slate-800">
                Request additional research (optional)
              </span>
              <textarea
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
                placeholder="e.g. Need deeper valuation and competitor analysis"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows={2}
              />
            </label>
            <div className="mt-4 flex flex-wrap gap-3 border-t border-slate-100 pt-4">
              <button type="button" disabled={loading} onClick={() => onAction("approve")} className="btn-success">
                {loading ? "Processing…" : "Approve & finalize"}
              </button>
              <button type="button" disabled={loading} onClick={() => onAction("reject")} className="btn-secondary">
                Reject
              </button>
              <button
                type="button"
                disabled={loading}
                onClick={() => onAction("request_analysis", { feedback })}
                className="btn-secondary"
              >
                Request more research
              </button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return null;
}
