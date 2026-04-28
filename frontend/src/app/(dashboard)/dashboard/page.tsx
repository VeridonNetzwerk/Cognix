"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type BotStatus = {
  online: boolean;
  latency_ms?: number | null;
  guild_count: number;
  user_count: number;
  uptime_seconds: number;
  memory_mb: number;
  version: string;
};

function fmtUptime(s: number) {
  const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <p className="label">{label}</p>
      <p className="text-2xl font-semibold mt-1">{value}</p>
    </div>
  );
}

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["bot.status"],
    queryFn: () => api.get<BotStatus>("/api/v1/bot/status"),
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="text-fg-muted text-sm">Live bot status and quick metrics.</p>
      </div>
      {isLoading || !data ? (
        <div className="text-fg-muted">Loading…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat label="Status" value={data.online ? "🟢 Online" : "🔴 Offline"} />
          <Stat label="Latency" value={`${data.latency_ms ?? 0} ms`} />
          <Stat label="Guilds" value={String(data.guild_count)} />
          <Stat label="Users" value={String(data.user_count)} />
          <Stat label="Uptime" value={fmtUptime(data.uptime_seconds)} />
          <Stat label="Memory" value={`${data.memory_mb.toFixed(1)} MB`} />
          <Stat label="Version" value={data.version} />
        </div>
      )}
    </div>
  );
}
