"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    (async () => {
      try {
        const status = await api.get<{ configured: boolean }>("/api/v1/setup/status");
        if (!status.configured) {
          router.replace("/setup");
          return;
        }
        try {
          await api.get("/api/v1/auth/me");
          router.replace("/dashboard");
        } catch {
          router.replace("/login");
        }
      } catch {
        router.replace("/setup");
      }
    })();
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <p className="text-fg-muted">Loading…</p>
    </main>
  );
}
