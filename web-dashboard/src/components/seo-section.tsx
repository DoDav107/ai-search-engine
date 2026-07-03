"use client";

import { useMemo, useState } from "react";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
} from "framer-motion";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChevronDown, ArrowUpDown } from "lucide-react";
import {
  band,
  factorLabel,
  GLASS,
  type FactorResult,
  type PageReport,
  type Report,
} from "@/lib/report";
import { Section, sectionItem } from "./section";

function StatusPill({ status }: { status: string }) {
  const color =
    status === "pass"
      ? "var(--color-success)"
      : status === "warn"
        ? "var(--color-warning)"
        : "var(--color-danger)";
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide"
      style={{
        color,
        backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 35%, transparent)`,
      }}
    >
      {status}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  const reduce = useReducedMotion();
  const { color } = band(score);
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <motion.div
        className="h-full rounded-full"
        style={{ backgroundColor: color }}
        initial={{ width: reduce ? `${score}%` : 0 }}
        animate={{ width: `${score}%` }}
        transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
      />
    </div>
  );
}

function PageRow({ page }: { page: PageReport }) {
  const [open, setOpen] = useState(false);
  const { color } = band(page.score);
  return (
    <div className="border-t border-white/10 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="grid w-full cursor-pointer grid-cols-[1fr_auto] items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.06] sm:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_auto]"
      >
        <span className="flex items-center gap-2 truncate font-mono text-sm text-foreground/90">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: color }}
            aria-hidden
          />
          <span className="truncate" title={page.url}>
            {page.url}
          </span>
        </span>
        <span className="hidden items-center gap-3 sm:flex">
          <ScoreBar score={page.score} />
        </span>
        <span className="flex items-center gap-2 justify-self-end">
          <span className="font-mono text-sm font-semibold tabular-nums" style={{ color }}>
            {page.score.toFixed(1)}%
          </span>
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden
          />
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <ul className="space-y-2 px-4 pb-4 pt-1">
              {page.factors.length === 0 && (
                <li className="text-sm text-muted-foreground">
                  This page was crawled but was not scoreable.
                </li>
              )}
              {page.factors.map((f: FactorResult) => (
                <li
                  key={f.id}
                  className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2"
                >
                  <StatusPill status={f.status} />
                  <span className="min-w-0">
                    <span className="text-sm font-medium">{factorLabel(f.id)}</span>
                    <span className="block text-sm text-muted-foreground">{f.message}</span>
                  </span>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

type SortKey = "score" | "url";

export function SeoSection({ report, showAssessment = true }: { report: Report; showAssessment?: boolean }) {
  const pages = useMemo(() => report.seo_report?.pages ?? [], [report.seo_report?.pages]);
  const scoredPages = useMemo(() => pages.filter((page) => page.factors.length > 0), [pages]);
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [asc, setAsc] = useState(true); // score ascending = worst pages first (actionable)

  const sorted = useMemo(() => {
    const arr = [...pages];
    arr.sort((a, b) =>
      sortKey === "score" ? a.score - b.score : a.url.localeCompare(b.url)
    );
    return asc ? arr : arr.reverse();
  }, [pages, sortKey, asc]);

  const factorData = useMemo(() => {
    const map = new Map<string, { factor: string; fail: number; warn: number }>();
    for (const p of scoredPages) {
      for (const f of p.factors) {
        if (f.status !== "fail" && f.status !== "warn") continue;
        const e = map.get(f.id) ?? { factor: factorLabel(f.id), fail: 0, warn: 0 };
        if (f.status === "fail") e.fail += 1;
        else e.warn += 1;
        map.set(f.id, e);
      }
    }
    return [...map.values()].sort((a, b) => b.fail + b.warn - (a.fail + a.warn));
  }, [scoredPages]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  }

  return (
    <Section
      title="SEO Breakdown"
      subtitle={`${scoredPages.length} pages scored · ${pages.length} pages crawled · site score ${(report.seo_report?.score ?? report.seo_score ?? 0).toFixed(1)}%`}
    >
      {pages.length === 0 && (
        <motion.div variants={sectionItem} className={`${GLASS} mb-6 p-5 text-sm text-muted-foreground sm:p-6`}>
          No SEO page data is stored in this report yet. Run a new audit from the dashboard.
        </motion.div>
      )}
      {showAssessment && report.seo_assessment && (
        <motion.div variants={sectionItem} className={`${GLASS} mb-6 p-5 sm:p-6`}>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Assessment
          </p>
          <p className="mt-2 text-sm leading-relaxed text-foreground/85">
            {report.seo_assessment}
          </p>
        </motion.div>
      )}
      {pages.length > 0 && scoredPages.length === 0 && (
        <motion.div variants={sectionItem} className={`${GLASS} mb-6 p-5 sm:p-6`}>
          <p className="text-sm text-muted-foreground">
            The audit ran, but no scoreable SEO pages were returned for this site.
          </p>
        </motion.div>
      )}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        {/* Factor summary chart */}
        <motion.div variants={sectionItem} className={`${GLASS} p-5 sm:p-6`}>
          <h3 className="text-sm font-medium text-muted-foreground">
            Issues by on-page factor
          </h3>
          <div className="mt-4 h-[300px] w-full">
            {factorData.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {scoredPages.length === 0
                  ? "No scored pages yet."
                  : "No failing or warning factors — every scored page passes."}
              </p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={factorData}
                  layout="vertical"
                  margin={{ top: 0, right: 16, bottom: 0, left: 8 }}
                  barCategoryGap={10}
                >
                  <XAxis
                    type="number"
                    allowDecimals={false}
                    tick={{ fill: "var(--color-muted-foreground)", fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="factor"
                    width={104}
                    tick={{ fill: "var(--color-muted-foreground)", fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: "rgba(255,255,255,0.04)" }}
                    contentStyle={{
                      background: "#0d1320",
                      border: "1px solid rgba(255,255,255,0.12)",
                      borderRadius: 12,
                      fontSize: 12,
                    }}
                    labelStyle={{ color: "var(--color-foreground)" }}
                  />
                  <Bar dataKey="warn" stackId="a" fill="var(--color-warning)" name="Warn" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="fail" stackId="a" fill="var(--color-danger)" name="Fail" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-3 flex items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--color-warning)" }} />
              Warn
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--color-danger)" }} />
              Fail
            </span>
          </div>
        </motion.div>

        {/* Sortable per-page table */}
        <motion.div variants={sectionItem} className={`${GLASS} overflow-hidden`}>
          <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
            <button
              type="button"
              onClick={() => toggleSort("url")}
              className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Page URL <ArrowUpDown className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => toggleSort("score")}
              className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Score {sortKey === "score" ? (asc ? "↑" : "↓") : ""}
              <ArrowUpDown className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {sorted.map((page) => (
              <PageRow key={page.url} page={page} />
            ))}
          </div>
        </motion.div>
      </div>
    </Section>
  );
}
