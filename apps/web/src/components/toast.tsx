"use client";

import { CheckCircle2, AlertTriangle, X } from "lucide-react";
import { createContext, useCallback, useContext, useState } from "react";
import { ApiError } from "@/lib/api";

type Toast = { id: number; kind: "success" | "error"; title: string; body?: string };
const Ctx = createContext<{ success: (t: string, b?: string) => void; error: (e: unknown, fallback?: string) => void } | null>(null);

const HINTS: Record<string, string> = {
  upgrade_plan: "Ask your company owner to change the plan in Settings → Subscription.",
  enable_module: "An admin can enable this module in Settings → Modules.",
  ask_admin: "Ask your administrator for access.",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 5000);
  }, []);
  const success = useCallback((title: string, body?: string) => push({ kind: "success", title, body }), [push]);
  const error = useCallback(
    (e: unknown, fallback = "Something went wrong") => {
      const err = e as ApiError;
      push({ kind: "error", title: err?.message || fallback, body: err?.actionHint ? HINTS[err.actionHint] : err?.code });
    },
    [push],
  );
  return (
    <Ctx.Provider value={{ success, error }}>
      {children}
      <div className="no-print fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="flex gap-3 rounded-lg border border-line bg-white p-3 shadow-lg">
            {t.kind === "success" ? <CheckCircle2 className="h-5 w-5 shrink-0 text-green-600" /> : <AlertTriangle className="h-5 w-5 shrink-0 text-red-600" />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{t.title}</p>
              {t.body && <p className="mt-0.5 text-xs text-muted">{t.body}</p>}
            </div>
            <button onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))} aria-label="Dismiss">
              <X className="h-4 w-4 text-muted" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useToast outside provider");
  return c;
}
