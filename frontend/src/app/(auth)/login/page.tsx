"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      await api.post("/api/v1/auth/login", { username, password, otp: otp || undefined });
      router.replace("/dashboard");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={submit} className="card w-full max-w-md space-y-5">
        <div>
          <h1 className="text-2xl font-semibold">Sign in to CogniX</h1>
          <p className="text-sm text-fg-muted">Use your administrator credentials.</p>
        </div>
        <div className="space-y-2">
          <label className="label">Username</label>
          <input className="input" autoComplete="username"
            value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <label className="label">Password</label>
          <input className="input" type="password" autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <label className="label">2FA code (if enabled)</label>
          <input className="input" inputMode="numeric" maxLength={6}
            value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="123456" />
        </div>
        {err && <div className="text-danger text-sm">{err}</div>}
        <button type="submit" className="btn-primary w-full" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
