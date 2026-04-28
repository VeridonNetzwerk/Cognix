"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Entry = {
  id: string; actor_id: string | null; action: string;
  target: string; ip_address: string; details: any; created_at: string;
};

export default function AuditPage() {
  const { data } = useQuery({
    queryKey: ["audit"],
    queryFn: () => api.get<Entry[]>("/api/v1/audit?limit=200"),
    refetchInterval: 15_000,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Audit log</h1>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-fg-muted">
            <tr className="border-b border-border">
              <th className="text-left py-2 pr-3">Time</th>
              <th className="text-left py-2 pr-3">Action</th>
              <th className="text-left py-2 pr-3">Target</th>
              <th className="text-left py-2 pr-3">Actor</th>
              <th className="text-left py-2 pr-3">IP</th>
              <th className="text-left py-2">Details</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((e) => (
              <tr key={e.id} className="border-b border-border/50">
                <td className="py-2 pr-3 text-fg-muted whitespace-nowrap">
                  {new Date(e.created_at).toLocaleString()}
                </td>
                <td className="py-2 pr-3 font-mono">{e.action}</td>
                <td className="py-2 pr-3">{e.target}</td>
                <td className="py-2 pr-3">{e.actor_id?.slice(0, 8) ?? "—"}</td>
                <td className="py-2 pr-3">{e.ip_address}</td>
                <td className="py-2 text-xs">
                  <code>{JSON.stringify(e.details)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
