"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Check, X, CircleSlash } from "lucide-react";
import {
  band,
  GLASS,
  isNoAnswer,
  prominence,
  type EngineQuality,
  type EngineScore,
  type GeoResult,
  type Report,
} from "@/lib/report";
import { Section, sectionItem } from "./section";

// "AI Engine / Model GEO Breakdown" — visibility tracked separately per engine/model.
// Backward compatible: with no engine_scores, falls back to a single "—/—" row built
// from the overall GEO score so older reports still render.
function keyLabel(src?: string): string {
  if (src === "env") return "saved";
  if (src === "temporary") return "temporary";
  return "none";
}

function EngineBreakdown({ engines, overall }: { engines: EngineScore[]; overall: number }) {
  const rows: EngineScore[] =
    engines.length > 0
      ? [...engines].sort((a, b) => (a.provider + a.model).localeCompare(b.provider + b.model))
      : [{ provider: "—", model: "—", geo_score: overall, visibility_rate: NaN, queries_run: 0, api_key_source: "none", web_grounded: undefined }];

  const grounded = engines.filter((e) => !e.error && e.queries_run && e.web_grounded);
  const ungrounded = engines.filter((e) => !e.error && e.queries_run && e.web_grounded === false);

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
          Visibility differs across ChatGPT, Claude, Gemini, Grok, Perplexity… The headline GEO
          score averages only the <span className="text-foreground">live-grounded</span> engines.
        </p>
      </div>
      <div className="mt-3">
        {rows.map((e, i) => {
          const score = e.geo_score ?? 0;
          const vis = Number.isFinite(e.visibility_rate)
            ? `${(Math.round(e.visibility_rate * 1000) / 10).toFixed(1)}%`
            : "N/A";
          const groundBadge =
            e.web_grounded === undefined
              ? null
              : e.web_grounded
                ? { text: "🌐 Live search", cls: "text-success" }
                : { text: "⚠ Model knowledge", cls: "text-warning" };
          return (
            <div
              key={`${e.provider}-${e.model}-${i}`}
              className="flex flex-wrap items-center justify-between gap-4 border-t border-white/10 px-5 py-3 sm:px-6"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{e.provider}</span>
                  {groundBadge && (
                    <span className={`text-[10px] font-medium ${groundBadge.cls}`}>{groundBadge.text}</span>
                  )}
                </div>
                <div className="truncate font-mono text-xs text-muted-foreground" title={e.model}>
                  {e.model}
                </div>
              </div>
              <div className="flex items-center gap-5 sm:gap-6">
                {stat("GEO score", `${score.toFixed(1)}%`, band(score).color)}
                {stat("Visibility", vis)}
                {stat("Sources", String(e.sources_count ?? 0))}
                {stat("Queries", String(e.queries_run ?? 0))}
                {stat("API key", keyLabel(e.api_key_source))}
              </div>
              {e.grounding_warning ? (
                <p className="w-full text-xs text-warning">⚠ {e.grounding_warning}</p>
              ) : null}
              {e.error ? <p className="w-full text-xs text-warning">⚠ {e.error}</p> : null}
            </div>
          );
        })}
      </div>
      {engines.length > 0 && (
        <div className="border-t border-white/10 px-5 py-3 text-xs text-muted-foreground sm:px-6">
          Headline GEO score = average of {grounded.length} live-grounded engine(s).
          {ungrounded.length > 0 && (
            <> Excluded (ungrounded): {ungrounded.map((e) => `${e.provider}/${e.model}`).join(", ")}.</>
          )}
        </div>
      )}
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

function QualityMetric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-lg tabular-nums">{value}</div>
      {note && <div className="mt-0.5 text-[10px] text-muted-foreground/80">{note}</div>}
    </div>
  );
}

// Backward compat: build a quality block from old per-query rows (no stored `quality`).
// Competitor names weren't ranked in old reports, so the breakdown/leaders stay empty.
function legacyQuality(measured: GeoResult[]): EngineQuality | null {
  const rows = measured.filter((r) => r.per_query_geo_score != null);
  if (rows.length === 0) return null;
  const men = rows.filter((r) => r.brand_mentioned);
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  const ranks = men.map((r) => r.brand_rank_position).filter((v): v is number => typeof v === "number");
  const cites = rows.filter((r) => r.citations_present).length;
  return {
    answers_total: rows.length,
    brand_mentions: men.length,
    sov: rows.length ? men.length / rows.length : 0,
    sentiment: {
      avg: avg(men.map((r) => r.sentiment_score ?? 0)),
      positive: men.filter((r) => r.sentiment_label === "positive").length,
      neutral: men.filter((r) => r.sentiment_label === "neutral").length,
      negative: men.filter((r) => r.sentiment_label === "negative").length,
    },
    recommendation: { avg: avg(men.map((r) => r.recommendation_score ?? 0)) },
    avg_brand_rank: ranks.length ? avg(ranks) : null,
    citations_answers: cites,
    citation_coverage: rows.length ? cites / rows.length : 0,
    competitor_total: rows.reduce((a, r) => a + (r.competitor_count ?? 0), 0),
    top_competitors: [],
    competitor_leaders: [],
  };
}

// One engine's quality block, rendered with EXPLICIT denominators (see Python
// build_engine_quality — same math/labels on both dashboards).
function QualityBlockCard({ q, label }: { q: EngineQuality; label?: string }) {
  const nAll = q.answers_total ?? 0;
  const nMen = q.brand_mentions ?? 0;
  const avgSent = q.sentiment?.avg ?? null;
  const avgRec = q.recommendation?.avg ?? null;
  const avgRank = q.avg_brand_rank ?? null;
  const citeCov = (q.citation_coverage ?? 0) * 100;
  const top = q.top_competitors ?? [];
  const leaders = q.competitor_leaders ?? [];
  const brandNote = nMen === 0 ? "brand not mentioned" : "of brand mentions";
  const allNote = `across all ${nAll} answers`;

  return (
    <div className={label ? "border-t border-white/10 pt-5 first:border-t-0 first:pt-0" : ""}>
      {label && <p className="text-sm font-medium text-foreground">{label}</p>}
      <p className="mt-1 text-xs text-muted-foreground">
        Share of Voice:{" "}
        <span className="font-semibold text-foreground">{Math.round((q.sov ?? 0) * 100)}%</span> — brand
        mentioned in {nMen} of {nAll} answers.
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <QualityMetric label="Avg sentiment" value={nMen === 0 || avgSent === null ? "N/A" : `${avgSent >= 0 ? "+" : ""}${avgSent.toFixed(2)}`} note={brandNote} />
        <QualityMetric label="Avg recommendation" value={nMen === 0 || avgRec === null ? "N/A" : `${Math.round(avgRec * 100)}%`} note={brandNote} />
        <QualityMetric label="Citation coverage" value={`${Math.round(citeCov)}%`} note={allNote} />
        <QualityMetric label="Competitor mentions" value={String(q.competitor_total ?? 0)} note={allNote} />
        <QualityMetric label="Avg brand rank" value={nMen === 0 || avgRank === null ? "N/A" : `#${avgRank.toFixed(1)}`} note={brandNote} />
      </div>
      {nMen > 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Sentiment of {nMen} brand mention(s):{" "}
          <span className="text-success">🟢 {q.sentiment.positive} positive</span> ·{" "}
          <span>⚪ {q.sentiment.neutral} neutral</span> ·{" "}
          <span className="text-danger">🔴 {q.sentiment.negative} negative</span>.
        </p>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">
          🔴 <span className="font-medium text-foreground">N/A — brand not mentioned</span> in any of the{" "}
          {nAll} answers for this engine.
        </p>
      )}
      {top.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-muted-foreground">Top competitors across all {nAll} answers (by # answers mentioning):</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {top.map((c) => (
              <span key={c.name} className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs">
                {c.name} <span className="tabular-nums text-muted-foreground">{c.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      {nMen === 0 && leaders.length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-muted-foreground">
            Brand absent — <span className="font-medium text-foreground">who won these answers and how strongly</span>:
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted-foreground">
                <tr className="text-left">
                  <th className="py-1 pr-4 font-medium">Competitor</th>
                  <th className="py-1 pr-4 font-medium">Mentions</th>
                  <th className="py-1 pr-4 font-medium">Sentiment</th>
                  <th className="py-1 pr-4 font-medium">Recommendation</th>
                  <th className="py-1 font-medium">Best rank</th>
                </tr>
              </thead>
              <tbody>
                {leaders.map((d) => (
                  <tr key={d.name} className="border-t border-white/10">
                    <td className="py-1 pr-4 text-foreground/90">{d.name}</td>
                    <td className="py-1 pr-4 tabular-nums">{d.mentions}</td>
                    <td className="py-1 pr-4">{d.sentiment_label}</td>
                    <td className="py-1 pr-4">{d.recommendation_strength}</td>
                    <td className="py-1 tabular-nums">{d.rank ? `#${d.rank}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// "GEO Quality Signals" — per engine, beyond mention/no-mention: HOW the brand is
// mentioned, with consistent denominators. Falls back to a single legacy block for
// older reports without a stored per-engine `quality` block.
function QualitySignals({ engines, measured }: { engines: EngineScore[]; measured: GeoResult[] }) {
  const qEngines = engines.filter((e) => e.quality);
  let blocks: { label?: string; q: EngineQuality }[];
  if (qEngines.length > 0) {
    const multi = qEngines.length > 1;
    blocks = [...qEngines]
      .sort((a, b) => (a.provider + a.model).localeCompare(b.provider + b.model))
      .map((e) => ({ label: multi ? `${e.provider} / ${e.model}` : undefined, q: e.quality as EngineQuality }));
  } else {
    const legacy = legacyQuality(measured);
    blocks = legacy ? [{ q: legacy }] : [];
  }
  if (blocks.length === 0) return null;

  return (
    <motion.div variants={sectionItem} className={`${GLASS} mt-6 p-5 sm:p-6`}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        GEO Quality Signals
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        Brand-mention metrics (sentiment · recommendation · rank) are over answers that{" "}
        <span className="text-foreground/90">mention the brand</span>; citation coverage and competitor
        mentions are over <span className="text-foreground/90">all answers</span>.
      </p>
      <div className="mt-4 space-y-5">
        {blocks.map((b, i) => (
          <QualityBlockCard key={b.label ?? i} q={b.q} label={b.label} />
        ))}
      </div>
    </motion.div>
  );
}

// Region badge: which locale grounded this query's search. Missing/global → "Global".
function LocaleBadge({ r }: { r: GeoResult }) {
  const code = (r.locale_applied || "global").toString();
  const label = code === "global" ? "Global" : code;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
      title={`Region: ${label}${r.locale_method && r.locale_method !== "none" ? ` (${r.locale_method})` : ""}`}
    >
      🌍 {label}
    </span>
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
          <span className="flex items-center gap-1.5">
            <span className="truncate">{r.query}</span>
            <LocaleBadge r={r} />
          </span>
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
              <div className="flex items-center gap-2 text-xs">
                <span className="uppercase tracking-wide text-muted-foreground">Region:</span>
                <LocaleBadge r={r} />
                {r.locale_method && r.locale_method !== "none" && (
                  <span className="text-muted-foreground">via {r.locale_method.replace("_", " ")}</span>
                )}
              </div>
              {(r.per_query_geo_score != null || (r.sentiment_label && r.sentiment_label !== "unknown")) && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>Sentiment: <span className="text-foreground/90">{r.sentiment_label ?? "unknown"}</span></span>
                  <span>Recommendation: <span className="text-foreground/90">{r.recommendation_strength ?? "unknown"}</span></span>
                  <span>Brand rank: <span className="text-foreground/90">{r.brand_rank_position != null ? `#${r.brand_rank_position}` : "N/A"}</span></span>
                  <span>Citations: <span className="text-foreground/90">{r.citations_present ? `yes (${r.citation_count ?? 0})` : "no"}</span></span>
                  <span>Quality score: <span className="text-foreground/90">{r.per_query_geo_score != null ? `${r.per_query_geo_score.toFixed(1)}%` : "N/A"}</span></span>
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

export function GeoSection({ report, showAssessment = true }: { report: Report; showAssessment?: boolean }) {
  const reduce = useReducedMotion();
  const results = useMemo(() => report.geo_report?.results ?? [], [report.geo_report?.results]);
  const brand = report.geo_report?.brand ?? report.brand ?? "Subject";
  const sov = report.geo_report?.share_of_voice ?? [];
  const sovHeadline = report.geo_report?.sov_headline ?? "";
  const geoScore = report.geo_report?.geo_score ?? report.geo_score ?? 0;
  const selectedProvider = report.audit_settings?.geo_provider;
  const selectedModel = report.audit_settings?.geo_model;

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
      {(selectedProvider || selectedModel) && (
        <motion.p variants={sectionItem} className="mb-4 text-sm text-muted-foreground">
          Measured using:{" "}
          <span className="font-medium text-foreground">
            {[selectedProvider, selectedModel].filter(Boolean).join(" / ")}
          </span>
        </motion.p>
      )}
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

        {showAssessment && report.geo_assessment && (
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

      {/* GEO Quality Signals — per engine: sentiment, recommendation, citations, rank, SoV */}
      <QualitySignals engines={report.geo_report?.engine_scores ?? []} measured={measured} />

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
