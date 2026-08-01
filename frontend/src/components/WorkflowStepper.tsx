const STEPS = [
  { id: "validate", label: "Validate" },
  { id: "plan", label: "Plan" },
  { id: "research", label: "Research" },
  { id: "thesis", label: "Thesis & Safety" },
  { id: "committee", label: "Committee" },
  { id: "review", label: "Human review" },
  { id: "report", label: "Report" },
];

function stepIndex(
  status?: string,
  awaitingHuman?: boolean,
  checkpointType?: string,
  hasReport?: boolean,
): number {
  if (!status) return 0;
  if (status === "complete" || status === "approved") return 6;
  if (awaitingHuman && checkpointType === "checkpoint_2_committee_review") {
    return hasReport ? 6 : 5;
  }
  if (awaitingHuman && checkpointType === "checkpoint_1_company_confirmation") return 0;
  if (awaitingHuman && status === "validating") return 0;
  if (status.includes("committee") || status === "awaiting_committee_review") return 4;
  if (status.includes("safety")) return 3;
  if (status === "researching" || status === "research_complete") return 2;
  if (status === "planned") return 1;
  return 0;
}

export function WorkflowStepper({
  status,
  awaitingHuman,
  checkpointType,
  hasReport,
}: {
  status?: string;
  awaitingHuman?: boolean;
  checkpointType?: string;
  hasReport?: boolean;
}) {
  const active = stepIndex(status, awaitingHuman, checkpointType, hasReport);
  const atCommitteeReview =
    awaitingHuman && checkpointType === "checkpoint_2_committee_review" && hasReport;

  return (
    <nav aria-label="Research progress">
      <ol className="flex flex-wrap items-center gap-1 sm:gap-0">
        {STEPS.map((step, i) => {
          const done = i < active || (atCommitteeReview && i === 5);
          const current = i === active && !(atCommitteeReview && i === 5);
          const reportReady = atCommitteeReview && i === 6;

          return (
            <li key={step.id} className="flex items-center">
              <div
                className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  reportReady
                    ? "bg-emerald-600 text-white"
                    : current
                      ? "bg-brand text-white shadow-sm"
                      : done
                        ? "text-emerald-700"
                        : "text-slate-400"
                }`}
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                    reportReady
                      ? "bg-white/25"
                      : current
                        ? "bg-white/25"
                        : done
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-slate-100"
                  }`}
                >
                  {done || reportReady ? "✓" : i + 1}
                </span>
                <span className="hidden sm:inline">{step.label}</span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`mx-1 hidden h-px w-4 sm:block ${done || reportReady ? "bg-emerald-300" : "bg-slate-200"}`}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
