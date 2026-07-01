"use client";

import { createContext, useContext, type ReactNode } from "react";

// Lightweight controlled tabs (shadcn-style, no extra dependency). The active value is
// owned by the parent so it survives data refreshes/re-runs (it isn't reset on refetch).
type TabsCtx = { value: string; onValueChange: (v: string) => void };
const Ctx = createContext<TabsCtx | null>(null);

export function Tabs({
  value,
  onValueChange,
  children,
  className,
}: {
  value: string;
  onValueChange: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Ctx.Provider value={{ value, onValueChange }}>
      <div className={className}>{children}</div>
    </Ctx.Provider>
  );
}

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      role="tablist"
      className={
        "inline-flex flex-wrap items-center gap-1 rounded-2xl border border-white/10 bg-white/[0.04] p-1 backdrop-blur-md " +
        (className ?? "")
      }
    >
      {children}
    </div>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("TabsTrigger must be used within <Tabs>");
  const active = ctx.value === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={() => ctx.onValueChange(value)}
      className={
        "cursor-pointer rounded-xl px-3.5 py-1.5 text-sm font-medium transition-colors sm:px-4 " +
        (active
          ? "bg-white/[0.10] text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground")
      }
    >
      {children}
    </button>
  );
}

// Panels stay MOUNTED (only hidden via CSS when inactive) so switching tabs never
// refetches or resets child state (e.g. the Trends client/date-range selection).
export function TabsContent({ value, children }: { value: string; children: ReactNode }) {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("TabsContent must be used within <Tabs>");
  const active = ctx.value === value;
  return (
    <div role="tabpanel" hidden={!active} className={active ? "" : "hidden"}>
      {children}
    </div>
  );
}
