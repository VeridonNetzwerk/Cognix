"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type CogState = { name: string; enabled: boolean; loaded?: boolean };

export default function CogsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["cogs"],
    queryFn: () => api.get<CogState[]>("/api/v1/cogs"),
    refetchInterval: 8000,
  });

  async function action(name: string, action: "load" | "unload" | "reload") {
    await api.post(`/api/v1/cogs/${name}`, { action });
    qc.invalidateQueries({ queryKey: ["cogs"] });
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Cogs</h1>
      {isLoading ? (
        <p className="text-fg-muted">Loading…</p>
      ) : (
        <div className="card divide-y divide-border">
          {data?.map((c) => (
            <div key={c.name} className="flex items-center justify-between py-3">
              <div>
                <p className="font-medium">{c.name}</p>
                <p className="text-xs text-fg-muted">
                  {c.loaded ? "🟢 loaded" : "⚪ not loaded"}
                  {c.enabled ? "" : " · disabled"}
                </p>
              </div>
              <div className="flex gap-2">
                <button className="btn-ghost" onClick={() => action(c.name, "reload")}>Reload</button>
                {c.loaded
                  ? <button className="btn-danger" onClick={() => action(c.name, "unload")}>Unload</button>
                  : <button className="btn-primary" onClick={() => action(c.name, "load")}>Load</button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
