import type { ResearchPlan, TaskStatus } from "@/lib/types";

const STATE_STYLE: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  degraded: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
  skipped: "bg-slate-100 text-slate-500",
  pending: "bg-slate-50 text-slate-400",
};

function labelCapability(cap: string) {
  return cap.replace(/\./g, " · ").replace(/_/g, " ");
}

export function PlanPanel({
  plan,
  taskStatus,
}: {
  plan: ResearchPlan;
  taskStatus: Record<string, TaskStatus>;
}) {
  const tasks = plan.tasks || [];

  return (
    <section className="card">
      <h2 className="section-title">Research plan</h2>
      <p className="mb-4 text-sm text-slate-600">
        <span className="font-medium text-slate-800">
          {plan.industry_profile?.display_name || plan.classification}
        </span>{" "}
        research strategy
        {plan.industry && <> · {plan.industry}</>}
      </p>
      {plan.industry_profile?.business_model && (
        <p className="mb-3 text-xs text-slate-500">{plan.industry_profile.business_model}</p>
      )}
      {plan.planner_rationale && (
        <p className="mb-4 rounded-lg bg-slate-50 p-3 text-sm leading-relaxed text-slate-600">
          {plan.planner_rationale}
        </p>
      )}
      <ul className="space-y-2">
        {tasks.map((task) => {
          const st = taskStatus[task.task_id]?.state || "pending";
          const cls = STATE_STYLE[st] || STATE_STYLE.pending;
          return (
            <li
              key={task.task_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2"
            >
              <div>
                <p className="text-sm font-medium text-slate-800">{labelCapability(task.capability)}</p>
                {task.rationale && <p className="text-xs text-slate-500">{task.rationale}</p>}
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{st}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
