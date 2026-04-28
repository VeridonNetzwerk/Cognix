"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Settings = {
  bot_status_text: string;
  bot_status_type: string;
  bot_description: string;
  features: Record<string, boolean>;
};

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { api.get<Settings>("/api/v1/settings").then(setS).catch(() => {}); }, []);

  async function save() {
    if (!s) return;
    setSaving(true);
    try { await api.patch("/api/v1/settings", s); } finally { setSaving(false); }
  }

  if (!s) return <p className="text-fg-muted">Loading…</p>;

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <div className="card space-y-4">
        <div>
          <p className="label">Status text</p>
          <input className="input mt-1" value={s.bot_status_text}
            onChange={(e) => setS({ ...s, bot_status_text: e.target.value })} />
        </div>
        <div>
          <p className="label">Status type</p>
          <select className="input mt-1" value={s.bot_status_type}
            onChange={(e) => setS({ ...s, bot_status_type: e.target.value })}>
            {["playing","watching","listening","competing"].map((t) =>
              <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <p className="label">Bot description</p>
          <textarea className="input mt-1" rows={3} value={s.bot_description}
            onChange={(e) => setS({ ...s, bot_description: e.target.value })} />
        </div>
        <button className="btn-primary" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
