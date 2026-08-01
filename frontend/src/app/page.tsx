"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { listRuns, startRun } from "@/lib/api";
import type { RunSummary } from "@/lib/types";

const EXAMPLES = ["NVDA", "AAPL", "MSFT", "JPM", "AMZN"];

export default function HomePage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<RunSummary[]>([]);
  const router = useRouter();

  useEffect(() => {
    listRuns(8)
      .then((r) => setRecent(r.runs))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const suggested = new URLSearchParams(window.location.search).get("q");
    if (suggested) {
      setQuery(suggested);
    }
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await startRun(query.trim());
      router.push(`/run/${result.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start research run");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-10 lg:grid-cols-5">
      <div className="lg:col-span-3">
        <h1 className="mb-3 text-3xl font-bold tracking-tight text-slate-900">
          Institutional-grade research, agent-orchestrated
        </h1>
        <p className="mb-8 max-w-xl text-slate-600 leading-relaxed">
          Enter a public company ticker or name. Multi-agent specialists gather cited evidence, a
          living thesis evolves, an investment committee debates, and you approve before any report
          is finalized.
        </p>

        <form onSubmit={handleSubmit} className="card mb-4">
          <label htmlFor="query" className="mb-2 block text-sm font-medium text-slate-700">
            Company or ticker
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              id="query"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. NVDA"
              className="flex-1 rounded-lg border border-slate-300 px-4 py-3 text-lg focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
              disabled={loading}
            />
            <button type="submit" disabled={loading || !query.trim()} className="btn-primary px-8 py-3">
              {loading ? "Starting…" : "Start research"}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setQuery(t)}
                className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
              >
                {t}
              </button>
            ))}
          </div>
        </form>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>
        )}
      </div>

      <aside className="lg:col-span-2">
        <div className="card mb-4">
          <h2 className="section-title">How it works</h2>
          <ol className="space-y-3 text-sm text-slate-600">
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/10 text-xs font-bold text-brand">1</span>
              Confirm the correct public company (HITL)
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/10 text-xs font-bold text-brand">2</span>
              Planner builds industry-specific research tasks
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/10 text-xs font-bold text-brand">3</span>
              Specialist agents gather parallel evidence
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/10 text-xs font-bold text-brand">4</span>
              Bull / Bear / CIO committee debates
            </li>
            <li className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand/10 text-xs font-bold text-brand">5</span>
              You approve the recommendation (HITL)
            </li>
          </ol>
        </div>

        {recent.length > 0 && (
          <div className="card">
            <h2 className="section-title">Recent runs</h2>
            <ul className="divide-y divide-slate-100">
              {recent.map((run) => (
                <li key={run.run_id}>
                  <Link
                    href={`/run/${run.run_id}`}
                    className="flex items-center justify-between py-2 text-sm hover:text-brand"
                  >
                    <span className="font-medium">{run.company_name || run.ticker || run.query}</span>
                    <span className="text-xs text-slate-400">{run.status}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>
    </div>
  );
}
