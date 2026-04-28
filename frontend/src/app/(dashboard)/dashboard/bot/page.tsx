"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function BotControlPage() {
  const { data, refetch } = useQuery({
    queryKey: ["bot.status"],
    queryFn: () => api.get<any>("/api/v1/bot/status"),
    refetchInterval: 4000,
  });

  async function restart() {
    if (!confirm("Restart the bot process?")) return;
    await api.post("/api/v1/bot/restart");
    refetch();
  }

  return (
    <div className="space-y-6 max-w-xl">
      <h1 className="text-2xl font-semibold">Bot control</h1>
      <div className="card space-y-3">
        <p className="label">Live status</p>
        <pre className="text-xs bg-bg-muted rounded p-3 overflow-auto">
{JSON.stringify(data ?? {}, null, 2)}
        </pre>
        <button className="btn-danger" onClick={restart}>Restart bot</button>
      </div>
    </div>
  );
}
