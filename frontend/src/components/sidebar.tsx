"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import {
  Activity, Bot, Cog, FileLock, Gauge, Hammer, LayoutDashboard, MessageSquare,
  Music2, Settings, Shield, Ticket, Users
} from "lucide-react";

const NAV: { section: string; items: { href: string; label: string; icon: any }[] }[] = [
  {
    section: "Server Management",
    items: [
      { href: "/dashboard",          label: "Overview",     icon: LayoutDashboard },
      { href: "/dashboard/servers",  label: "Servers",      icon: Bot },
      { href: "/dashboard/users",    label: "Users",        icon: Users },
      { href: "/dashboard/moderation", label: "Moderation", icon: Shield },
      { href: "/dashboard/tickets",  label: "Tickets",      icon: Ticket },
    ],
  },
  {
    section: "Utilities",
    items: [
      { href: "/dashboard/cogs",     label: "Cogs",         icon: Cog },
      { href: "/dashboard/stats",    label: "Stats",        icon: Activity },
      { href: "/dashboard/backups",  label: "Backups",      icon: FileLock },
      { href: "/dashboard/audit",    label: "Audit Log",    icon: Gauge },
    ],
  },
  {
    section: "Engagement & Fun",
    items: [
      { href: "/dashboard/music",    label: "Music",        icon: Music2 },
      { href: "/dashboard/messages", label: "Messages",     icon: MessageSquare },
    ],
  },
  {
    section: "System",
    items: [
      { href: "/dashboard/bot",      label: "Bot control",  icon: Hammer },
      { href: "/dashboard/settings", label: "Settings",     icon: Settings },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-64 shrink-0 bg-bg-soft border-r border-border h-screen sticky top-0 flex flex-col">
      <div className="px-5 py-5 flex items-center gap-2 border-b border-border">
        <div className="w-8 h-8 rounded-lg bg-brand grid place-items-center font-bold">C</div>
        <span className="text-lg font-semibold">CogniX</span>
      </div>
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
        {NAV.map((s) => (
          <div key={s.section}>
            <p className="label px-3 mb-2">{s.section}</p>
            <ul className="space-y-0.5">
              {s.items.map((it) => {
                const Icon = it.icon;
                const active = pathname === it.href;
                return (
                  <li key={it.href}>
                    <Link
                      href={it.href}
                      className={clsx(
                        "flex items-center gap-3 px-3 py-2 rounded-md text-sm",
                        active
                          ? "bg-brand text-white"
                          : "text-fg hover:bg-bg-muted",
                      )}
                    >
                      <Icon size={16} />
                      <span>{it.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
