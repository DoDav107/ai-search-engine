"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Check, X, CircleSlash } from "lucide-react";
import {
  band,
  GLASS,
  isNoAnswer,
  prominence,
  type EngineScore,
  type GeoResult,
  type Report,
} from "@/lib/report";
import { Section, sectionItem } from "./section";

// "AI Engine / Model GEO Breakdown" — visibility tracked separately per engine/model.
// Backward compatible: with no engine_scores, falls back to a single "—/—" row built
// from the overall GEO score so older reports still render.
function EngineBreakdown({ engines, overall }: { engines: EngineScore[]; overall: number }) {
  const rows: EngineScore[] =
    engines.length > 0
      ? engines
      : [{ provider: "—", model: "—", geo_score: overall, visibility_rate: NaN, queries_run: 0 }];

  const stat = (label: string, value: string, color?: string) => (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="font-mono text-sm tabular-nums" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  );

  return (
    <motion.div variants={sectionItem} className={`${GLASS} mt-6 overflow-hidden`}>
      <div className="px-5 pt-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          AI Engine / Model GEO Breakdown
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Visibility can differ across ChatGPT, Claude, Perplexity… Overall is the average of enabled engines.
        </p>
      </div>
      <div className="mt-3">
        {rows.map((e, i) => {
          const score = e.geo_score ?? 0;
          const vis = Number.isFinite(e.visibility_rate)
            ? `${(Math.round(e.visibility_rate * 1000) / 10).toFixed(1)}%`
            : "N/A";
          return (
            <div
              key={`${e.provider}-${e.model}-${i}`}
              className="flex flex-wrap items-center justify-between gap-4 border-t border-white/10 px-5 py-3 sm:px-6"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-foreground">{e.provider}</div>
                <div className="truncate font-mono text-xs text-muted-foreground" title={e.model}>
                  {e.model}
                </div>
              </div>
              <div className="flex items-center gap-6">
                {stat("GEO score", `${score.toFixed(1)}%`, band(score).color)}
                {stat("Visibility", vis)}
                {stat("Queries", String(e.queries_run ?? 0))}
              </div>
              {e.error ? (
                <p className="w-full text-xs text-warning">⚠ {e.error}</p>
              ) : null}
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}

function MentionIndicator({ r }: { r: GeoResult }) {
  if (isNoAnswer(r)) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium"
        style={{
          color: "var(--color-warning)",
          backgroundColor: "color-mix(in srgb, var(--color-warning) 14%, transparent)",
          border: "1px solid color-mix(in srgb, var(--color-warning) 35%, transparent)",
        }}
      >
        <CircleSlash className="h-3 w-3" aria-hidden /> No answer
      </span>
    );
  }
  if (r.brand_mentioned) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-success">
        <Check className="h-3.5 w-3.5" aria-hidden /> Mentioned
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
      <X className="h-3.5 w-3.5" aria-hidden /> Not mentioned
    </span>
  );
}

function ProminenceBar({ value }: { value: number }) {
  const reduce = useReducedMotion();
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: "var(--color-brand)" }}
          initial={{ width: reduce ? `${value}%` : 0 }}
          whileInView={{ width: `${value}%` }}
          viewport={{ once: true }}
          transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
      <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
        {value.toFixed(1)}%
      </span>
    </div>
  );
}

function QueryRow({ r }: { r: GeoResult }) {
  const [open, setOpen] = useState(false);
  const noAnswer = isNoAnswer(r);
  const prom = prominence(r);
  const excerpt = (r.answer || "").trim().slice(0, 420);

  return (
    <div className="border-t border-white/10 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="grid w-full cursor-pointer grid-cols-[1fr_auto] items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-white/[0.06] sm:grid-cols-[minmax(0,2fr)_140px_minmax(0,1.3fr)_auto]"
      >
        <span className="min-w-0 truncate text-sm text-foreground/90" title={r.query}>
          {r.query}
          {r.model ? (
            <span className="block truncate font-mono text-[10px] text-muted-foreground">
              {[r.provider, r.model].filter(Boolean).join(" / ")}
            </span>
          ) : null}
        </span>
        <span className="hidden sm:block">
          <MentionIndicator r={r} />
        </span>
        <span className="hidden sm:block">
          {prom !== null ? (
            <ProminenceBar value={prom} />
          ) : (
            <span className="font-mono text-xs text-muted-foreground">—</span>
          )}
        </span>
        <ChevronDown
          className={`h-4 w-4 justify-self-end text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
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
            <div className="space-y-3 px-4 pb-4 pt-1">
              <div className="sm:hidden">
                <MentionIndicator r={r} />
              </div>
              {(r.provider || r.model) && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="uppercase tracking-wide text-muted-foreground">Engine:</span>
                  <span className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 font-mono">
                    {[r.provider, r.model].filter(Boolean).join(" / ")}
                  </span>
                </div>
              )}
              {noAnswer ? (
                <p className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-foreground/90">
                  This query returned no answer{r.error ? ` (${r.error})` : ""} — excluded
                  from Brand Visibility and the GEO score, not counted as a miss.
                </p>
              ) : (
                <>
                  <div>
                    <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      AI answer excerpt
                    </p>
                    <p className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm leading-relaxed text-foreground/90">
                      {excerpt}
                      {(r.answer || "").length > 420 ? "…" : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Competitors named:
                    </span>
                    {r.competitors_found.length > 0 ? (
                      r.competitors_found.map((c) => (
                        <span
                          key={c}
                          className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-xs"
                        >
                          {c}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-muted-foreground">none detected</span>
                    )}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function GeoSection({ report }: { report: Report }) {
  const reduce = useReducedMotion();
  const results = useMemo(() => report.geo_report?.results ?? [], [report.geo_report?.results]);
  const brand = report.geo_report?.brand ?? report.brand ?? "Subject";
  const sov = report.geo_report?.share_of_voice ?? [];
  const sovHeadline = report.geo_report?.sov_headline ?? "";
  const geoScore = report.geo_report?.geo_score ?? report.geo_score ?? 0;

  const { measured, noAnswer, mentioned, visibility } = useMemo(() => {
    const measured = results.filter((r) => !isNoAnswer(r));
    const noAnswer = results.length - measured.length;
    const mentioned = measured.filter((r) => r.brand_mentioned).length;
    const visibility = measured.length
      ? Math.round((mentioned / measured.length) * 1000) / 10
      : 0;
    return { measured, noAnswer, mentioned, visibility };
  }, [results]);

  return (
    <Section
      title="GEO Report"
      subtitle="How often AI engines surface the brand for target queries"
    >
      {results.length === 0 && (
        <motion.div variants={sectionItem} className={`${GLASS} mb-6 p-5 text-sm text-muted-foreground sm:p-6`}>
          No GEO query results are stored in this report yet. Run a new audit from the dashboard.
        </motion.div>
      )}
      {/* Summary row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <motion.div variants={sectionItem} className={`${GLASS} p-5 sm:p-6`}>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Brand Visibility
              </p>
              <p className="mt-1 font-mono text-4xl font-semibold tabular-nums text-glow">
                {visibility.toFixed(1)}
                <span className="ml-0.5 text-xl text-muted-foreground">%</span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {mentioned} of {measured.length} measured
                {noAnswer > 0 ? ` · ${noAnswer} no-answer excluded` : ""}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                GEO Score
              </p>
              <p
                className="mt-1 font-mono text-4xl font-semibold tabular-nums"
                style={{ color: "var(--color-brand)" }}
              >
                {geoScore.toFixed(1)}
                <span className="ml-0.5 text-xl text-muted-foreground">%</span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Prominence-weighted across queries
              </p>
            </div>
          </div>
        </motion.div>

        {report.geo_assessment && (
          <motion.div variants={sectionItem} className={`${GLASS} p-5 sm:p-6`}>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Assessment
            </p>
            <p className="mt-2 text-sm leading-relaxed text-foreground/85">
              {report.geo_assessment}
            </p>
          </motion.div>
        )}
      </div>

      {/* AI Engine / Model GEO Breakdown */}
      <EngineBreakdown engines={report.geo_report?.engine_scores ?? []} overall={geoScore} />

      {/* Share of Voice — ranked brands (subject + competitors) by presence */}
      {sov.length > 0 && (() => {
        const TOPN = 15;
        let shown = sov.slice(0, TOPN);
        if (!shown.some((s) => s.is_subject)) {
          const subj = sov.find((s) => s.is_subject);
          if (subj) shown = [...shown, subj];
        }
        return (
          <motion.div variants={sectionItem} className={`${GLASS} mt-6 p-5 sm:p-6`}>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Share of Voice
            </p>
            {sovHeadline && (
              <p className="mt-1 text-base font-semibold text-foreground">🏆 {sovHeadline}</p>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              Share of measured queries where each brand appears — {brand} highlighted.
            </p>
            <div className="mt-4 space-y-2">
              {shown.map((s) => {
                const pct = Math.round(s.share * 1000) / 10;
                return (
                  <div
                    key={s.brand}
                    className="grid grid-cols-[minmax(0,130px)_1fr_auto] items-center gap-3"
                  >
                    <span
                      className={`truncate text-sm ${s.is_subject ? "font-semibold text-foreground" : "text-foreground/80"}`}
                      title={s.brand}
                    >
                      {s.brand}
                      {s.is_subject ? " ★" : ""}
                    </span>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                      <motion.div
                        className="h-full rounded-full"
                        style={{
                          backgroundColor: s.is_subject
                            ? "var(--color-brand)"
                            : "rgba(148,163,184,0.55)",
                        }}
                        initial={{ width: reduce ? `${pct}%` : 0 }}
                        whileInView={{ width: `${pct}%` }}
                        viewport={{ once: true }}
                        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
                      />
                    </div>
                    <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
                      {pct.toFixed(0)}%
                    </span>
                  </div>
                );
              })}
            </div>
          </motion.div>
        );
      })()}

      {/* Per-query table */}
      <motion.div variants={sectionItem} className={`${GLASS} mt-6 overflow-hidden`}>
        <div className="hidden grid-cols-[minmax(0,2fr)_140px_minmax(0,1.3fr)_auto] gap-4 border-b border-white/10 px-4 py-3 text-xs font-medium text-muted-foreground sm:grid">
          <span>Query</span>
          <span>Brand</span>
          <span>Prominence</span>
          <span />
        </div>
        <div>
          {results.map((r, i) => (
            <QueryRow key={`${r.query}-${i}`} r={r} />
          ))}
        </div>
      </motion.div>
    </Section>
  );
}
