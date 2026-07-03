"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ArrowDown, ArrowUp, Minus, Info, Trash2, Loader2, AlertTriangle } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  GLASS,
  type TrendQueryPoint,
  type TrendRun,
  type TrendsClients,
  type TrendsSeries,
} from "@/lib/report";
import { Section, sectionItem } from "./section";

// Line colours mirror the Streamlit trends view.
const SERIES = [
  { key: "unified", label: "Unified", color: "var(--color-primary)" },
  { key: "seo", label: "SEO", color: "#38bdf8" },
  { key: "geo", label: "GEO", color: "var(--color-success)" },
  { key: "brand_visibility", label: "Brand visibility", color: "var(--color-warning)" },
] as const;

const SOV_COLORS = ["var(--color-primary)", "#38bdf8", "var(--color-warning)", "var(--color-danger)"];

function slugify(name: string): string {
  return (name || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
}

function fmtLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(d);
}
function fmtDay(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

function ChangeCard({
  label,
  cur,
  prev,
  lowConfidence,
}: {
  label: string;
  cur: number | null;
  prev: number | null;
  lowConfidence: boolean;
}) {
  const delta = cur != null && prev != null ? Math.round((cur - prev) * 10) / 10 : null;
  const Arrow = delta == null || delta === 0 ? Minus : delta > 0 ? ArrowUp : ArrowDown;
  const deltaColor =
    delta == null || delta === 0 ? "var(--color-muted-foreground)" : delta > 0 ? "var(--color-success)" : "var(--color-danger)";
  return (
    <div className={`${GLASS} p-4`}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-2xl tabular-nums">{cur != null ? `${cur.toFixed(1)}%` : "—"}</div>
      {delta != null ? (
        <div className="mt-1 flex items-center gap-1 text-xs" style={{ color: deltaColor }}>
          <Arrow className="h-3.5 w-3.5" aria-hidden />
          <span className="font-medium tabular-nums">{Math.abs(delta).toFixed(1)}</span>
          <span className="text-muted-foreground">
            {lowConfidence ? "vs earlier today (variance)" : "vs prev"}
          </span>
        </div>
      ) : (
        <div className="mt-1 text-xs text-muted-foreground">— no prior</div>
      )}
    </div>
  );
}

function NoiseBands({ rows }: { rows: { label: string; low: boolean }[] }) {
  // Shade each interval whose run is flagged same-day/low-confidence (a "noise band").
  return (
    <>
      {rows.map((row, i) =>
        i > 0 && row.low ? (
          <ReferenceArea
            key={`band-${i}`}
            x1={rows[i - 1].label}
            x2={row.label}
            fill="var(--color-warning)"
            fillOpacity={0.07}
            ifOverflow="extendDomain"
          />
        ) : null,
      )}
    </>
  );
}

const AXIS = { fill: "var(--color-muted-foreground)", fontSize: 11 } as const;
const TOOLTIP = {
  contentStyle: { background: "#0d1320", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, fontSize: 12 },
  labelStyle: { color: "var(--color-foreground)" },
} as const;

export function TrendsSection({ defaultClient }: { defaultClient?: string }) {
  const [clients, setClients] = useState<string[]>([]);
  const [client, setClient] = useState<string>("");
  const [series, setSeries] = useState<TrendsSeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [from, setFrom] = useState<string>("");
  const [to, setTo] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  // "Remove client" confirm modal + in-flight/errored delete state.
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Load the client list, selecting `preferred` (slug) when it exists, else the first
  // remaining client (or none). Reused on mount AND after a delete so both surfaces reflect
  // the same source and the view never points at a now-missing client.
  const loadClients = useCallback((preferred?: string) => {
    return fetch("/api/trends", { cache: "no-store" })
      .then((r) => r.json())
      .then((data: TrendsClients) => {
        const list = data.clients ?? [];
        setClients(list);
        const want = preferred && list.includes(preferred) ? preferred : "";
        setClient(want || list[0] || "");
        return list;
      })
      .catch((e) => {
        setError(String(e));
        return [] as string[];
      });
  }, []);

  // Initial load: preselect the current report's client when present.
  useEffect(() => {
    let cancelled = false;
    loadClients(defaultClient ? slugify(defaultClient) : undefined).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [defaultClient, loadClients]);

  // Load the selected client's series. Deferred via a macrotask so the effect body
  // doesn't call setState synchronously (matches the dashboard's loadReport pattern).
  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    const id = window.setTimeout(() => {
      setLoading(true);
      fetch(`/api/trends?client=${encodeURIComponent(client)}`, { cache: "no-store" })
        .then((r) => r.json())
        .then((data: TrendsSeries) => {
          if (cancelled) return;
          setSeries(data);
          setError(null);
          const runs = data.runs ?? [];
          setFrom(runs.length ? fmtDay(runs[0].timestamp) : "");
          setTo(runs.length ? fmtDay(runs[runs.length - 1].timestamp) : "");
          setQuery(data.queries?.[0] ?? "");
        })
        .catch((e) => setError(String(e)))
        .finally(() => setLoading(false));
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [client]);

  // Filter runs to the chosen date range, keeping original indices for query alignment.
  // INCLUSIVE on both ends, compared as real UTC timestamps (not strings): from the start
  // date 00:00:00Z through the end date 23:59:59.999Z. This matches Streamlit's UTC
  // ts.date() basis and avoids the end-date being treated as exclusive.
  const filtered = useMemo(() => {
    const runs = series?.runs ?? [];
    const fromMs = from ? Date.parse(`${from}T00:00:00Z`) : Number.NEGATIVE_INFINITY;
    const toMs = to ? Date.parse(`${to}T23:59:59.999Z`) : Number.POSITIVE_INFINITY;
    return runs
      .map((r, idx) => ({ r, idx }))
      .filter(({ r }) => {
        const t = Date.parse(r.timestamp);
        return Number.isNaN(t) ? true : t >= fromMs && t <= toMs;
      });
  }, [series, from, to]);

  const chartData = useMemo(
    () =>
      filtered.map(({ r }) => ({
        label: fmtLabel(r.timestamp),
        low: r.low_confidence,
        unified: r.unified,
        seo: r.seo,
        geo: r.geo,
        brand_visibility: r.brand_visibility,
      })),
    [filtered],
  );

  // How many saved runs the confirm dialog will warn are being permanently removed.
  const runCount = series?.runs?.length ?? 0;

  async function handleDeleteClient() {
    if (!client) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await fetch("/api/clients/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client }),
      });
      const data = await res.json();
      if (!res.ok) {
        setDeleteError(data.error ?? "Could not remove the client.");
        return;
      }
      setConfirmDelete(false);
      // The deleted client is gone from the shared source, so this picks another/none —
      // the view never stays pointed at a now-missing client.
      await loadClients();
    } catch (e) {
      setDeleteError(String(e));
    } finally {
      setDeleting(false);
    }
  }

  const clientSelect = (
    <div className="flex items-center gap-2">
      <select
        value={client}
        onChange={(e) => setClient(e.target.value)}
        className="rounded-xl border border-white/10 bg-[#111827] px-3 py-2 text-sm outline-none focus:border-primary/60"
      >
        {clients.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => {
          setDeleteError(null);
          setConfirmDelete(true);
        }}
        disabled={!client}
        title="Remove this client"
        aria-label="Remove this client"
        className="inline-flex items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] p-2 text-muted-foreground transition-colors hover:border-danger/40 hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Trash2 className="h-4 w-4" aria-hidden />
      </button>

      {/* Mandatory confirmation — no one-click destructive delete. */}
      {confirmDelete && client && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Confirm remove client"
          onClick={() => !deleting && setConfirmDelete(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0d1320] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center gap-2 text-danger">
              <AlertTriangle className="h-5 w-5" aria-hidden />
              <h3 className="text-base font-semibold">Remove client</h3>
            </div>
            <p className="text-sm text-foreground/85">
              Permanently remove <span className="font-mono font-semibold">{client}</span> and its{" "}
              <span className="font-semibold">{runCount}</span> saved run{runCount === 1 ? "" : "s"}?
              This deletes that client&apos;s report history from disk and cannot be undone from here.
            </p>
            {deleteError && (
              <p className="mt-3 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
                {deleteError}
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-sm font-medium text-foreground transition-colors hover:bg-white/[0.08] disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteClient}
                disabled={deleting}
                className="inline-flex items-center gap-2 rounded-xl border border-danger/40 bg-danger/15 px-3.5 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger/25 disabled:opacity-50"
              >
                {deleting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Trash2 className="h-4 w-4" aria-hidden />}
                {deleting ? "Removing…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  if (!loading && clients.length === 0) {
    return (
      <Section title="Trends over time" subtitle="Scores, visibility and prominence across saved runs">
        <motion.div variants={sectionItem} className={`${GLASS} p-5 text-sm text-muted-foreground sm:p-6`}>
          No saved history yet — run an audit to start building trends.
        </motion.div>
      </Section>
    );
  }

  const runs = series?.runs ?? [];
  const inverted = !!(from && to && from > to);
  const hasRuns = filtered.length > 0;             // ≥1 run → the chart MUST render
  const enough = filtered.length >= 2;             // ≥2 → change-since-previous deltas
  const last = filtered.length ? filtered[filtered.length - 1].r : null;
  const prev = filtered.length >= 2 ? filtered[filtered.length - 2].r : null;
  const lastLow = !!last?.low_confidence;

  return (
    <Section
      title="Trends over time"
      subtitle="Scores, visibility and prominence across saved runs"
      action={clientSelect}
    >
      {error && (
        <motion.div variants={sectionItem} className={`${GLASS} mb-4 p-4 text-sm text-danger`}>
          {error}
        </motion.div>
      )}

      {/* Date range */}
      {runs.length > 0 && (
        <motion.div variants={sectionItem} className="mb-5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span className="uppercase tracking-wide">Date range</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-sm outline-none focus:border-primary/60" />
          <span>→</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-sm outline-none focus:border-primary/60" />
        </motion.div>
      )}

      {/* Empty / inverted-range states — never a silent blank chart. */}
      {inverted ? (
        <motion.div variants={sectionItem} className={`${GLASS} p-5 text-sm text-muted-foreground sm:p-6`}>
          Start date is after end date — adjust the range.
        </motion.div>
      ) : !hasRuns ? (
        <motion.div variants={sectionItem} className={`${GLASS} p-5 text-sm text-muted-foreground sm:p-6`}>
          No runs in this date range — widen the range to see saved runs.
        </motion.div>
      ) : (
        <>
          {/* Change-since-previous cards */}
          <motion.p variants={sectionItem} className="mb-3 text-xs text-muted-foreground">
            {enough ? "Change since previous run " : "Single run in range "}
            {prev && last && (
              <span className="font-mono">
                {fmtLabel(prev.timestamp)} → {fmtLabel(last.timestamp)}
              </span>
            )}
            {!enough && last && <span className="font-mono">{fmtLabel(last.timestamp)}</span>}
            {lastLow && (
              <span className="ml-2 inline-flex items-center gap-1 rounded-md border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-warning">
                <Info className="h-3 w-3" aria-hidden /> same-day — may reflect run-to-run variance
              </span>
            )}
            {last?.factor_set_shift && (
              <span className="ml-2 inline-flex items-center gap-1 rounded-md border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-warning">
                <Info className="h-3 w-3" aria-hidden /> different SEO factor set — SEO/Unified change isn&apos;t a real site change
              </span>
            )}
          </motion.p>
          <motion.div variants={sectionItem} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {SERIES.map((s) => (
              <ChangeCard
                key={s.key}
                label={s.label}
                cur={(last?.[s.key as keyof TrendRun] as number | null) ?? null}
                prev={(prev?.[s.key as keyof TrendRun] as number | null) ?? null}
                lowConfidence={lastLow}
              />
            ))}
          </motion.div>

          {/* Scores & visibility over time */}
          <motion.div variants={sectionItem} className={`${GLASS} mt-6 p-5 sm:p-6`}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Scores &amp; visibility over time</p>
              <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="h-2.5 w-3.5 rounded-sm" style={{ background: "var(--color-warning)", opacity: 0.25 }} />
                same-day / low-confidence (&lt; {series?.min_interval_hours ?? 24}h apart)
              </span>
            </div>
            <div className="h-[320px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 6, right: 16, bottom: 0, left: -8 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} minTickGap={20} />
                  <YAxis domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} width={36} />
                  <Tooltip {...TOOLTIP} />
                  <NoiseBands rows={chartData} />
                  {SERIES.map((s) => (
                    <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color}
                      strokeWidth={2.5} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
              {SERIES.map((s) => (
                <span key={s.key} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
                  {s.label}
                </span>
              ))}
            </div>
          </motion.div>

          {/* Share of Voice over time */}
          {series && series.sov.length > 0 && (
            <motion.div variants={sectionItem} className={`${GLASS} mt-6 p-5 sm:p-6`}>
              <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Share of Voice over time (you vs top competitors)
              </p>
              <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={filtered.map(({ idx, r }) => {
                      const row: Record<string, number | string | null> = { label: fmtLabel(r.timestamp), low: r.low_confidence ? 1 : 0 };
                      series.sov.forEach((s) => (row[s.name] = s.values[idx] ?? null));
                      return row;
                    })}
                    margin={{ top: 6, right: 16, bottom: 0, left: -8 }}
                  >
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                    <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} minTickGap={20} />
                    <YAxis domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} width={36} />
                    <Tooltip {...TOOLTIP} />
                    <NoiseBands rows={chartData} />
                    {series.sov.map((s, i) => (
                      <Line key={s.name} type="monotone" dataKey={s.name}
                        name={s.is_subject ? `${s.name} (you)` : s.name}
                        stroke={SOV_COLORS[i % SOV_COLORS.length]} strokeWidth={s.is_subject ? 3 : 2}
                        dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                {series.sov.map((s, i) => (
                  <span key={s.name} className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SOV_COLORS[i % SOV_COLORS.length] }} />
                    {s.is_subject ? `${s.name} (you)` : s.name}
                  </span>
                ))}
              </div>
            </motion.div>
          )}

          {/* Per-query drill-down */}
          {series && series.queries.length > 0 && (
            <motion.div variants={sectionItem} className={`${GLASS} mt-6 p-5 sm:p-6`}>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Per-query drill-down</p>
                <select
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="max-w-[60%] truncate rounded-lg border border-white/10 bg-[#111827] px-2 py-1 text-xs outline-none focus:border-primary/60"
                >
                  {series.queries.map((q) => (
                    <option key={q} value={q}>{q}</option>
                  ))}
                </select>
              </div>
              <QueryChart points={filtered.map(({ idx, r }) => ({ label: fmtLabel(r.timestamp), low: r.low_confidence, pt: series.query_series[query]?.[idx] }))} />
              <p className="mt-3 text-[11px] text-muted-foreground">
                Green dot = brand mentioned that run; red = absent. Shaded = same-day / low-confidence.
              </p>
            </motion.div>
          )}
        </>
      )}
    </Section>
  );
}

function QueryChart({ points }: { points: { label: string; low: boolean; pt?: TrendQueryPoint }[] }) {
  const data = points.map((p) => ({
    label: p.label,
    low: p.low,
    prominence: p.pt?.prominence ?? null,
    mentioned: !!p.pt?.mentioned,
  }));
  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 16, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} minTickGap={20} />
          <YAxis domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} width={36} />
          <Tooltip {...TOOLTIP} />
          <NoiseBands rows={data} />
          <Line
            type="monotone"
            dataKey="prominence"
            name="Prominence"
            stroke="var(--color-primary)"
            strokeWidth={2.5}
            connectNulls
            isAnimationActive={false}
            dot={(props: { cx?: number; cy?: number; payload?: { mentioned: boolean; prominence: number | null } }) => {
              const { cx, cy, payload } = props;
              if (cx == null || cy == null || payload?.prominence == null) {
                return <g key={`${cx}-${cy}`} />;
              }
              return (
                <circle
                  key={`${cx}-${cy}`}
                  cx={cx}
                  cy={cy}
                  r={4.5}
                  fill={payload.mentioned ? "var(--color-success)" : "var(--color-danger)"}
                  stroke="none"
                />
              );
            }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
