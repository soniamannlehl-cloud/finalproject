"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CheckpointPanel } from "@/components/CheckpointPanel";
import { EvidencePanel } from "@/components/EvidencePanel";
import { PlanPanel } from "@/components/PlanPanel";
import { RecommendationSummary, ReportPanel } from "@/components/ReportPanel";
import { SafetyPanel } from "@/components/SafetyPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { ThesisPanel } from "@/components/ThesisPanel";
import { WorkflowStepper } from "@/components/WorkflowStepper";
import {
  getEvidence,
  getPlan,
  getRecommendation,
  getRun,
  getSafety,
  getThesis,
  resumeRun,
} from "@/lib/api";
import type {
  Checkpoint,
  EvidenceItem,
  Recommendation,
  ResearchPlan,
  RunState,
  StructuredThesis,
  TaskStatus,
  ThesisVersion,
} from "@/lib/types";

type SafetyData = {
  evidence_score?: number;
  is_blocking?: boolean;
  semantic_verified?: boolean;
  findings?: Array<{ check_name: string; severity: string; message: string }>;
  coverage?: { satisfied_capabilities?: string[]; required_capabilities?: string[] };
};

export default function RunPage() {
  const params = useParams();
  const runId = String(params.id);

  const [status, setStatus] = useState("loading");
  const [state, setState] = useState<RunState | null>(null);
  const [checkpoint, setCheckpoint] = useState<Checkpoint | null>(null);
  const [awaitingHuman, setAwaitingHuman] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const [plan, setPlan] = useState<ResearchPlan | null>(null);
  const [taskStatus, setTaskStatus] = useState<Record<string, TaskStatus>>({});
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [byCapability, setByCapability] = useState<Record<string, { count: number }>>({});
  const [thesisCurrent, setThesisCurrent] = useState<ThesisVersion | null>(null);
  const [thesisHistory, setThesisHistory] = useState<ThesisVersion[]>([]);
  const [thesisFramework, setThesisFramework] = useState<StructuredThesis | null>(null);
  const [safety, setSafety] = useState<SafetyData | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getRun(runId);
      setStatus(data.status);
      setState(data.state);
      setCheckpoint(data.checkpoint);
      setAwaitingHuman(data.awaiting_human);

      const [planData, evData, thesisData, safetyData, recData] = await Promise.all([
        getPlan(runId).catch(() => null),
        getEvidence(runId).catch(() => null),
        getThesis(runId).catch(() => null),
        getSafety(runId).catch(() => null),
        getRecommendation(runId).catch(() => null),
      ]);

      if (planData?.plan) {
        setPlan(planData.plan);
        setTaskStatus(planData.task_status || {});
      }
      if (evData) {
        setEvidence(evData.evidence || []);
        setByCapability(evData.by_capability || {});
      }
      if (thesisData) {
        setThesisCurrent(thesisData.current);
        setThesisHistory(thesisData.history || []);
        setThesisFramework(thesisData.framework || thesisData.current?.framework || null);
      }
      if (safetyData?.evidence_score !== undefined) {
        setSafety(safetyData);
      }
      if (recData?.recommendation) {
        setRecommendation(recData.recommendation);
      } else if (data.state?.recommendation) {
        setRecommendation(data.state.recommendation);
      }
    } catch {
      setStatus("error");
    }
  }, [runId]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, awaitingHuman ? 5000 : 3000);
    return () => clearInterval(interval);
  }, [refresh, awaitingHuman]);

  async function handleAction(action: string, extras?: { ticker?: string; feedback?: string }) {
    setActionLoading(true);
    try {
      const result = await resumeRun(runId, action, extras);
      setStatus(result.state?.status || "unknown");
      setState(result.state);
      setCheckpoint(result.checkpoint);
      setAwaitingHuman(result.awaiting_human);
    } finally {
      setActionLoading(false);
      await refresh();
    }
  }

  const isTerminal = ["complete", "approved", "rejected", "error", "validation_failed", "validation_rejected", "validation_unavailable"].includes(status);
  const validationFailed = ["validation_failed", "validation_rejected", "validation_unavailable"].includes(status);
  const title = state?.company_name || state?.ticker || state?.query || "Research run";
  const evidenceCount = state?.evidence_count ?? evidence.length;
  const hasReport = Boolean(state?.report_id || checkpoint?.report_id);
  const atCommitteeReview = awaitingHuman && checkpoint?.type === "checkpoint_2_committee_review";
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href="/" className="mb-2 inline-block text-sm text-brand hover:underline">
            ← New research
          </Link>
          <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
          <p className="text-sm text-slate-500">
            {state?.ticker && state?.company_name && `${state.ticker} · `}
            Run {runId}
          </p>
        </div>
        <StatusBadge status={status} />
      </div>

      <WorkflowStepper
        status={status}
        awaitingHuman={awaitingHuman}
        checkpointType={checkpoint?.type}
        hasReport={hasReport}
      />

      {validationFailed && (
        <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
          <h2 className="text-lg font-semibold text-amber-950">Company not found</h2>
          <p className="mt-2 text-sm text-amber-900">
            {state?.message || "We couldn't verify that company. Try the full name or ticker symbol."}
          </p>
          {state?.suggested_match && (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Link
                href={`/?q=${encodeURIComponent(state.suggested_match.ticker)}`}
                className="btn-primary px-4 py-2 text-sm"
              >
                Use {state.suggested_match.name} ({state.suggested_match.ticker})
              </Link>
              <span className="text-xs text-amber-800">Starts a new research run with the suggested company</span>
            </div>
          )}
          <Link href="/" className="mt-4 inline-block text-sm font-medium text-brand hover:underline">
            ← Try a different company
          </Link>
        </section>
      )}

      {awaitingHuman && checkpoint && (
        <CheckpointPanel
          checkpoint={checkpoint}
          onAction={handleAction}
          loading={actionLoading}
          thesisStatement={
            thesisFramework?.primary_thesis || thesisCurrent?.framework?.primary_thesis || thesisCurrent?.statement
          }
          thesisFramework={thesisFramework || checkpoint.thesis_framework}
          thesisConfidence={thesisCurrent?.confidence}
          safetyEvidenceScore={safety?.evidence_score}
        />
      )}

      {!awaitingHuman && !isTerminal && (
        <p className="rounded-lg bg-blue-50 px-4 py-3 text-center text-sm text-blue-800">
          Research in progress — this dashboard refreshes automatically every few seconds.
        </p>
      )}

      {!atCommitteeReview && (
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="metric card py-4">
            <p className="metric-label">Evidence gathered</p>
            <p className="metric-value">{evidenceCount}</p>
          </div>
          <div className="metric card py-4">
            <p className="metric-label">Evidence score</p>
            <p className="metric-value">
              {safety?.evidence_score?.toFixed(2) ?? state?.evidence_score?.toFixed(2) ?? "—"}
            </p>
          </div>
          <div className="metric card py-4">
            <p className="metric-label">Recommendation</p>
            <p className="text-lg font-bold uppercase text-slate-900">
              {(recommendation?.action || state?.recommendation?.action || "pending").replace(/_/g, " ")}
            </p>
          </div>
        </div>
      )}

      {atCommitteeReview && (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
          <button
            type="button"
            onClick={() => setShowDetails((v) => !v)}
            className="flex w-full items-center justify-between text-sm font-medium text-slate-700"
          >
            <span>Research details (thesis, evidence, safety)</span>
            <span className="text-slate-400">{showDetails ? "Hide ▲" : "Show ▼"}</span>
          </button>
        </div>
      )}

      {(!atCommitteeReview || showDetails) && plan && <PlanPanel plan={plan} taskStatus={taskStatus} />}

      {(!atCommitteeReview || showDetails) && (
        <div className="grid gap-6 lg:grid-cols-2">
          <ThesisPanel
            current={thesisCurrent}
            history={thesisHistory}
            framework={thesisFramework}
          />
          <EvidencePanel evidence={evidence} byCapability={byCapability} />
        </div>
      )}

      {(!atCommitteeReview || showDetails) && <SafetyPanel safety={safety} />}

      {(recommendation || state?.recommendation) && !awaitingHuman && (
        <RecommendationSummary recommendation={recommendation || state?.recommendation} />
      )}

      {(state?.report_id || checkpoint?.report_id) && !atCommitteeReview && (
        <ReportPanel runId={runId} reportId={state?.report_id || checkpoint?.report_id} />
      )}

      {!state?.report_id && isTerminal && status !== "error" && (
        <section className="card">
          <h2 className="section-title">Final investment report</h2>
          <p className="text-sm text-slate-600">
            No report was generated for this run. This can happen if the workflow was rejected before
            report generation or if report generation failed.
          </p>
        </section>
      )}

      {state?.errors && state.errors.length > 0 && (
        <section className="card border-red-200 bg-red-50/50">
          <h2 className="section-title text-red-900">Workflow errors</h2>
          <ul className="space-y-1 text-sm text-red-800">
            {state.errors.map((err, i) => (
              <li key={i}>
                <span className="font-medium">{err.stage}:</span> {err.error}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
