const STYLES: Record<string, string> = {
  awaiting_human: "bg-amber-100 text-amber-900 ring-amber-200",
  validating: "bg-slate-100 text-slate-700",
  validated: "bg-sky-100 text-sky-800",
  validation_failed: "bg-amber-100 text-amber-900 ring-amber-200",
  validation_rejected: "bg-amber-100 text-amber-900 ring-amber-200",
  validation_unavailable: "bg-red-100 text-red-800",
  planned: "bg-indigo-100 text-indigo-800",
  researching: "bg-blue-100 text-blue-800",
  committee_complete: "bg-violet-100 text-violet-800",
  approved: "bg-emerald-100 text-emerald-800",
  complete: "bg-emerald-100 text-emerald-800",
  rejected: "bg-red-100 text-red-800",
  error: "bg-red-100 text-red-800",
};

export function StatusBadge({ status }: { status?: string }) {
  const key = status || "unknown";
  const cls = STYLES[key] || "bg-slate-100 text-slate-700 ring-slate-200";
  return (
    <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ring-1 ${cls}`}>
      {key.replace(/_/g, " ")}
    </span>
  );
}
