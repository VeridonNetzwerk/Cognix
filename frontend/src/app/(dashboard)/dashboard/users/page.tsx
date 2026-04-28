"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type WebUser = {
  id: string; username: string; email: string | null;
  role: "ADMIN" | "MODERATOR" | "VIEWER"; is_active: boolean; totp_enabled: boolean;
};

export default function WebUsersPage() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["webusers"],
    queryFn: () => api.get<WebUser[]>("/api/v1/web-users"),
  });

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ username: "", email: "", password: "", role: "VIEWER" as WebUser["role"] });

  async function create() {
    await api.post("/api/v1/web-users", form);
    setForm({ username: "", email: "", password: "", role: "VIEWER" });
    setCreating(false);
    qc.invalidateQueries({ queryKey: ["webusers"] });
  }

  async function update(id: string, body: Partial<WebUser>) {
    await api.patch(`/api/v1/web-users/${id}`, body);
    qc.invalidateQueries({ queryKey: ["webusers"] });
  }

  async function remove(id: string) {
    if (!confirm("Delete this user?")) return;
    await api.delete(`/api/v1/web-users/${id}`);
    qc.invalidateQueries({ queryKey: ["webusers"] });
  }

  async function resetPw(id: string) {
    const np = prompt("New password (≥8 chars):");
    if (!np || np.length < 8) return;
    await api.post(`/api/v1/web-users/${id}/password`, { new_password: np });
  }

  async function disable2fa(id: string) {
    if (!confirm("Force-disable 2FA for this user?")) return;
    await api.post(`/api/v1/web-users/${id}/disable-2fa`);
    qc.invalidateQueries({ queryKey: ["webusers"] });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard users</h1>
        <button className="btn-primary" onClick={() => setCreating((v) => !v)}>
          {creating ? "Cancel" : "+ New user"}
        </button>
      </div>

      {creating && (
        <div className="card grid grid-cols-1 md:grid-cols-4 gap-3">
          <input className="input" placeholder="Username"
            value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input className="input" placeholder="Email" type="email"
            value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="input" placeholder="Password" type="password"
            value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <select className="input" value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value as WebUser["role"] })}>
            <option value="ADMIN">ADMIN</option>
            <option value="MODERATOR">MODERATOR</option>
            <option value="VIEWER">VIEWER</option>
          </select>
          <div className="md:col-span-4 flex justify-end">
            <button className="btn-primary" onClick={create}
              disabled={!form.username || form.password.length < 8}>Create</button>
          </div>
        </div>
      )}

      <div className="card divide-y divide-border">
        {data?.map((u) => (
          <div key={u.id} className="py-3 flex flex-wrap items-center gap-3 justify-between">
            <div className="min-w-[200px]">
              <p className="font-medium">{u.username}</p>
              <p className="text-xs text-fg-muted">{u.email || "—"} · {u.totp_enabled ? "🔒 2FA" : "no 2FA"}</p>
            </div>
            <select className="input max-w-[150px]" value={u.role}
              onChange={(e) => update(u.id, { role: e.target.value as WebUser["role"] })}>
              <option value="ADMIN">ADMIN</option>
              <option value="MODERATOR">MODERATOR</option>
              <option value="VIEWER">VIEWER</option>
            </select>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={u.is_active}
                onChange={(e) => update(u.id, { is_active: e.target.checked })} />
              Active
            </label>
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={() => resetPw(u.id)}>Reset PW</button>
              {u.totp_enabled && <button className="btn-ghost" onClick={() => disable2fa(u.id)}>Disable 2FA</button>}
              <button className="btn-danger" onClick={() => remove(u.id)}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
