"use client";

import { useEffect, useRef } from "react";

export function useEvents(onEvent: (e: { event: string; payload: unknown }) => void) {
  const ref = useRef<WebSocket | null>(null);
  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const base = process.env.NEXT_PUBLIC_API_BASE ?? `${proto}//${window.location.host}`;
    const url = base.replace(/^http/, "ws") + "/ws";
    const ws = new WebSocket(url);
    ref.current = ws;
    ws.onmessage = (m) => {
      try { onEvent(JSON.parse(m.data)); } catch {}
    };
    return () => ws.close();
  }, [onEvent]);
  return ref;
}
