"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Ticket = {
  id: string;
  server_id: string;
  opener_id: string;
  status: string;
  title: string;
  thread_id: string;
  closed_at: string | null;
};

export default function TicketsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["tickets"],
    queryFn: () => api.get<Ticket[]>("/api/v1/tickets"),
    refetchInterval: 10_000,
  });

  async function close(id: string) {
    await api.post(`/api/v1/tickets/${id}/close`);
    qc.invalidateQueries({ queryKey: ["tickets"] });
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Tickets</h1>
      {isLoading ? (
        <p className="text-fg-muted">Loading…</p>
      ) : !data?.length ? (
        <p className="text-fg-muted">No tickets yet.</p>
      ) : (
        <div className="card divide-y divide-border">
          {data.map((t) => (
            <div key={t.id} className="py-3 flex items-center justify-between">
              <div>
                <p className="font-medium">{t.title}</p>
                <p className="text-xs text-fg-muted">
                  #{t.id.slice(0, 8)} · server {t.server_id} · opener {t.opener_id} · {t.status}
                </p>
              </div>
              {t.status === "OPEN" && (
                <button className="btn-danger" onClick={() => close(t.id)}>Close</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
