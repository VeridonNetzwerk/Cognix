"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Server = { id: string; name: string; member_count: number; is_active: boolean; icon_url?: string | null };

export default function ServersPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["servers"],
    queryFn: () => api.get<Server[]>("/api/v1/servers"),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Servers</h1>
      {isLoading ? (
        <p className="text-fg-muted">Loading…</p>
      ) : !data?.length ? (
        <p className="text-fg-muted">No servers yet — invite the bot to a guild.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.map((s) => (
            <a key={s.id} href={`/dashboard/servers/${s.id}`} className="card hover:border-brand transition-colors">
              <div className="flex items-center gap-3">
                {s.icon_url ? (
                  <img src={s.icon_url} alt="" className="w-10 h-10 rounded-full" />
                ) : (
                  <div className="w-10 h-10 rounded-full bg-bg-muted grid place-items-center font-semibold">
                    {s.name.slice(0,1)}
                  </div>
                )}
                <div>
                  <p className="font-medium">{s.name}</p>
                  <p className="text-xs text-fg-muted">{s.member_count} members</p>
                </div>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
