"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { api, ApiError } from "@/lib/api";
import { LogOut } from "lucide-react";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<{ username: string; role: string } | null>(null);

  useEffect(() => {
    api.get<{ username: string; role: string }>("/api/v1/auth/me")
      .then(setUser)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 423) router.replace("/setup");
        else router.replace("/login");
      });
  }, [router]);

  async function logout() {
    try { await api.post("/api/v1/auth/logout"); } catch {}
    router.replace("/login");
  }

  if (!user) {
    return <div className="flex min-h-screen items-center justify-center text-fg-muted">Loading…</div>;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <header className="h-14 border-b border-border bg-bg-soft px-6 flex items-center justify-between">
          <span className="text-sm text-fg-muted">Welcome back, <span className="text-fg">{user.username}</span></span>
          <button className="btn-ghost gap-2" onClick={logout}>
            <LogOut size={14} /> Logout
          </button>
        </header>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
