"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Series = { name: string; points: { ts: string; value: number }[] };
type Overview = { series: Series[] };

function Spark({ s }: { s: Series }) {
  if (!s.points.length) return <p className="text-fg-muted text-sm">No data</p>;
  const max = Math.max(1, ...s.points.map((p) => p.value));
  return (
    <div className="flex items-end gap-0.5 h-16">
      {s.points.map((p, i) => (
        <div
          key={i}
          className="bg-brand/70 rounded-sm w-full"
          style={{ height: `${(p.value / max) * 100}%` }}
          title={`${p.ts}: ${p.value}`}
        />
      ))}
    </div>
  );
}

export default function StatsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: () => api.get<Overview>("/api/v1/stats/overview"),
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Statistics</h1>
      {isLoading ? (
        <p className="text-fg-muted">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data?.series.map((s) => (
            <div key={s.name} className="card">
              <p className="label">{s.name}</p>
              <p className="text-xl font-semibold mt-1">
                {s.points.reduce((a, b) => a + b.value, 0)}
              </p>
              <div className="mt-3"><Spark s={s} /></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
