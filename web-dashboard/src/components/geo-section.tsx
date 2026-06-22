"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Check, X, CircleSlash } from "lucide-react";
import {
  GLASS,
  isNoAnswer,
  prominence,
  type GeoResult,
  type Report,
} from "@/lib/report";
import { Section, sectionItem } from "./section";

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
        <span className="truncate text-sm text-foreground/90" title={r.query}>
          {r.query}
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
  const results = report.geo_report?.results ?? [];
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
