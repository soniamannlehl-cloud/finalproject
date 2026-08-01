export interface RunState {
  run_id: string;
  query?: string;
  ticker?: string;
  company_name?: string;
  sector?: string;
  industry?: string;
  status?: string;
  validation_status?: string;
  message?: string;
  suggested_match?: { ticker: string; name: string; exchange?: string };
  evidence_count?: number;
  evidence_score?: number;
  recommendation?: Recommendation;
  report_id?: string;
  classification?: string;
  plan_revision?: number;
  committee_decision?: string;
  errors?: Array<{ stage: string; error: string }>;
}

export interface Recommendation {
  action?: string;
  confidence?: number;
  evidence_score?: number;
  was_downgraded?: boolean;
  gate_reasons?: string[];
  bull_case?: { argument: string; conviction?: number };
  bear_case?: { argument: string; conviction?: number };
  cio_rationale?: string;
}

export interface Checkpoint {
  type: string;
  run_id?: string;
  prompt?: string;
  options?: string[];
  top_match?: { name: string; ticker: string; sector?: string; industry?: string };
  candidates?: Array<{ name: string; ticker: string; sector?: string }>;
  recommendation?: Recommendation;
  bull_case?: { argument: string };
  bear_case?: { argument: string };
  cio_rationale?: string;
  thesis_stance?: string;
  thesis_confidence?: number;
  thesis_statement?: string;
  thesis_framework?: StructuredThesis;
  research_summary?: string;
  evidence_score?: number;
  coverage_ratio?: number;
  failed_capabilities?: string[];
  report_id?: string;
}

export interface TaskSpec {
  task_id: string;
  capability: string;
  criticality: string;
  depends_on: string[];
  rationale?: string;
}

export interface ResearchPlan {
  classification?: string;
  industry?: string;
  sector?: string;
  planner_rationale?: string;
  tasks?: TaskSpec[];
  valuation_methods?: string[];
  industry_profile?: {
    display_name?: string;
    business_model?: string;
    investment_drivers?: string[];
    key_performance_indicators?: string[];
  };
}

export interface TaskStatus {
  state: string;
  capability?: string;
  error?: string;
  declared_gap?: boolean;
}

export interface EvidenceItem {
  evidence_id: string;
  capability: string;
  source_name?: string;
  source_url?: string;
  citation?: string;
  summary?: string;
  confidence?: number;
  provider_degraded?: boolean;
  retrieved_at?: string;
}

export interface StructuredThesis {
  core_question: string;
  primary_thesis: string;
  supporting_drivers: string[];
  key_risks: string[];
  positive_catalysts: string[];
  negative_catalysts: string[];
  valuation_opinion: string;
  confidence: number;
  missing_evidence: string[];
  recommendation: string;
  horizon?: string;
}

export interface ThesisVersion {
  version: number;
  statement: string;
  stance: string;
  confidence: number;
  change_reason?: string;
  created_at?: string;
  framework?: StructuredThesis | null;
}

export interface SafetyFinding {
  check_name: string;
  severity: string;
  message: string;
}

export interface RunSummary {
  run_id: string;
  status: string;
  query?: string;
  ticker?: string;
  company_name?: string;
  created_at?: string;
}
