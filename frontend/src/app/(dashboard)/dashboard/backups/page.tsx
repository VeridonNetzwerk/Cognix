"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Backup = { id: string; server_id: string; created_at: string; summary: any };

export default function BackupsPage() {
  const qc = useQueryClient();
  const [serverId, setServerId] = useState("");
  const { data } = useQuery({
    queryKey: ["backups"],
    queryFn: () => api.get<Backup[]>("/api/v1/backups"),
  });

  async function snapshot() {
    if (!serverId) return;
    await api.post("/api/v1/backups", { server_id: serverId });
    qc.invalidateQueries({ queryKey: ["backups"] });
  }

  async function restore(id: string) {
    const target = prompt("Target server ID to restore into:");
    if (!target) return;
    await api.post(`/api/v1/backups/${id}/restore`, { target_server_id: target });
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Backups</h1>
      <div className="card flex gap-3 items-end">
        <div className="flex-1">
          <p className="label">Server ID to snapshot</p>
          <input className="input mt-1" value={serverId}
            onChange={(e) => setServerId(e.target.value)} placeholder="e.g. 1234..." />
        </div>
        <button className="btn-primary" onClick={snapshot} disabled={!serverId}>
          Create snapshot
        </button>
      </div>
      <div className="card divide-y divide-border">
        {data?.length ? data.map((b) => (
          <div key={b.id} className="py-3 flex items-center justify-between">
            <div>
              <p className="font-medium">#{b.id.slice(0, 8)}</p>
              <p className="text-xs text-fg-muted">
                server {b.server_id} · {new Date(b.created_at).toLocaleString()}
              </p>
            </div>
            <button className="btn-ghost" onClick={() => restore(b.id)}>Restore…</button>
          </div>
        )) : <p className="text-fg-muted py-2">No backups yet.</p>}
      </div>
    </div>
  );
}
