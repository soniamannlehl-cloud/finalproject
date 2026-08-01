import type {
  Checkpoint,
  EvidenceItem,
  Recommendation,
  ResearchPlan,
  RunState,
  RunSummary,
  StructuredThesis,
  TaskStatus,
  ThesisVersion,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json();
}

export async function startRun(query: string) {
  return api<{
    run_id: string;
    awaiting_human: boolean;
    checkpoint: Checkpoint | null;
    state: RunState;
  }>("/runs", { method: "POST", body: JSON.stringify({ query }) });
}

export async function resumeRun(
  runId: string,
  action: string,
  extras?: { ticker?: string; feedback?: string },
) {
  return api<{
    run_id: string;
    awaiting_human: boolean;
    checkpoint: Checkpoint | null;
    state: RunState;
  }>(`/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify({ action, ...extras }),
  });
}

export async function getRun(runId: string) {
  return api<{
    run_id: string;
    status: string;
    awaiting_human: boolean;
    checkpoint: Checkpoint | null;
    state: RunState;
  }>(`/runs/${runId}`);
}

export async function listRuns(limit = 10) {
  return api<{ runs: RunSummary[]; count: number }>(`/runs?limit=${limit}`);
}

export async function getPlan(runId: string) {
  return api<{
    plan: ResearchPlan | null;
    task_status: Record<string, TaskStatus>;
    classification?: string;
    plan_revision?: number;
  }>(`/runs/${runId}/plan`);
}

export async function getEvidence(runId: string) {
  return api<{
    count: number;
    by_capability: Record<string, { count: number }>;
    evidence: EvidenceItem[];
  }>(`/runs/${runId}/evidence`);
}

export async function getThesis(runId: string) {
  return api<{
    current: ThesisVersion | null;
    framework?: StructuredThesis | null;
    history: ThesisVersion[];
    confidence_trajectory: Array<[number, number]>;
  }>(`/runs/${runId}/thesis`);
}

export async function getSafety(runId: string) {
  return api<{
    evidence_score?: number;
    is_blocking?: boolean;
    semantic_verified?: boolean;
    findings?: Array<{ check_name: string; severity: string; message: string }>;
    coverage?: { coverage_ratio?: number; satisfied_capabilities?: string[] };
  }>(`/runs/${runId}/safety`);
}

export async function getRecommendation(runId: string) {
  return api<{ recommendation: Recommendation | null; committee_decision?: string }>(
    `/runs/${runId}/recommendation`,
  );
}

export function reportPdfUrl(runId: string) {
  return `${API_BASE}/runs/${runId}/report/pdf`;
}

export function reportHtmlUrl(runId: string) {
  return `${API_BASE}/runs/${runId}/report/html`;
}
