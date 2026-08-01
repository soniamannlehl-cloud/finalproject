/** Strip internal claim/evidence tags from committee prose shown in the UI. */
export function cleanCommitteeText(text?: string): string {
  if (!text) return "";
  return text
    .replace(/\[(?:claim|ev)_[a-f0-9]+(?:_\w+)?\]/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function formatAction(action?: string): string {
  if (!action) return "Pending";
  return action.replace(/_/g, " ");
}

export function recommendationTone(action?: string): {
  badge: string;
  accent: string;
  label: string;
} {
  const key = (action || "").toLowerCase();
  if (key.includes("insufficient")) {
    return {
      badge: "bg-amber-100 text-amber-900 ring-amber-200",
      accent: "border-amber-400",
      label: "No directional call — evidence below threshold",
    };
  }
  if (key.includes("buy") || key.includes("overweight")) {
    return {
      badge: "bg-emerald-100 text-emerald-900 ring-emerald-200",
      accent: "border-emerald-500",
      label: "Constructive view",
    };
  }
  if (key.includes("sell") || key.includes("underweight")) {
    return {
      badge: "bg-red-100 text-red-900 ring-red-200",
      accent: "border-red-500",
      label: "Cautious view",
    };
  }
  if (key.includes("hold") || key.includes("neutral")) {
    return {
      badge: "bg-slate-100 text-slate-800 ring-slate-200",
      accent: "border-slate-400",
      label: "Neutral stance",
    };
  }
  return {
    badge: "bg-slate-100 text-slate-800 ring-slate-200",
    accent: "border-slate-300",
    label: "Committee verdict",
  };
}
