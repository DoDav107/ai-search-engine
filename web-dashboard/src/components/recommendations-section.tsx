"use client";

import { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Copy, Check, Zap } from "lucide-react";
import {
  GLASS,
  priorityColor,
  sortByPriority,
  type Recommendation,
  type Report,
} from "@/lib/report";
import { Section, sectionContainer, sectionItem } from "./section";

function PriorityBadge({ priority }: { priority: string }) {
  const color = priorityColor(priority);
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold"
      style={{
        color,
        backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 38%, transparent)`,
      }}
    >
      {priority}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-white/20 hover:text-foreground"
    >
      {copied ? (
        <>
          <Check className="h-3.5 w-3.5" aria-hidden /> Copied
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5" aria-hidden /> Copy
        </>
      )}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 text-sm leading-relaxed text-foreground/85">{children}</p>
    </div>
  );
}

function RecCard({ rec }: { rec: Recommendation }) {
  return (
    <motion.div variants={sectionItem} className={`${GLASS} flex flex-col gap-4 p-5 sm:p-6`}>
      <div className="flex items-start justify-between gap-3">
        <h4 className="text-base font-semibold leading-snug">{rec.title}</h4>
        <PriorityBadge priority={rec.priority} />
      </div>
      {rec.scope && (
        <p className="-mt-2 text-xs text-muted-foreground">{rec.scope}</p>
      )}
      <Field label="Issue">{rec.issue}</Field>
      <Field label="Why it matters">{rec.why_it_matters}</Field>
      <Field label="Recommendation">{rec.recommendation}</Field>

      {rec.draft && rec.draft.trim() && (
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Draft fix
            </p>
            <CopyButton text={rec.draft} />
          </div>
          <pre className="max-h-64 overflow-auto rounded-xl border border-white/10 bg-black/30 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-foreground/85">
            {rec.draft}
          </pre>
        </div>
      )}
    </motion.div>
  );
}

export function RecommendationsSection({ report }: { report: Report }) {
  const reduce = useReducedMotion();
  const seo = report.seo_recommendations ?? [];
  const geo = report.geo_recommendations ?? [];

  const seoSorted = sortByPriority(seo);
  const geoSorted = sortByPriority(geo);

  // Highest-priority items across BOTH areas for the Top Priority panel.
  const top = sortByPriority(
    [...seo, ...geo].map((r) => ({ ...r, area: r.area || "—" }))
  ).slice(0, 5);

  return (
    <>
      {/* Top Priority Actions */}
      <Section
        title="Top Priority Actions"
        subtitle="Highest-impact fixes across SEO and GEO"
      >
        <motion.div variants={sectionItem} className={`${GLASS} divide-y divide-white/10`}>
          {top.length === 0 && (
            <p className="p-5 text-sm text-muted-foreground">No recommendations available.</p>
          )}
          {top.map((rec, i) => {
            const color = priorityColor(rec.priority);
            return (
              <div key={`${rec.area}-${rec.title}-${i}`} className="flex items-center gap-3 p-4">
                <Zap className="h-4 w-4 shrink-0" style={{ color }} aria-hidden />
                <span
                  className="shrink-0 rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  {rec.area}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium" title={rec.title}>
                  {rec.title}
                </span>
                <span className="hidden truncate text-xs text-muted-foreground sm:block">
                  {rec.scope}
                </span>
                <PriorityBadge priority={rec.priority} />
              </div>
            );
          })}
        </motion.div>
      </Section>

      {/* SEO Recommendations */}
      <Section title="SEO Recommendations" subtitle={`${seoSorted.length} items`}>
        {seoSorted.length === 0 ? (
          <p className={`${GLASS} p-5 text-sm text-muted-foreground`}>
            No SEO recommendations are stored in this report yet. Run a new audit from the dashboard.
          </p>
        ) : (
          <motion.div
            initial={reduce ? "show" : "hidden"}
            whileInView="show"
            viewport={{ once: true, amount: 0.1 }}
            variants={sectionContainer}
            className="grid grid-cols-1 gap-5 lg:grid-cols-2"
          >
            {seoSorted.map((rec, i) => (
              <RecCard key={`seo-${rec.title}-${i}`} rec={rec} />
            ))}
          </motion.div>
        )}
      </Section>

      {/* GEO Recommendations */}
      <Section title="GEO Recommendations" subtitle={`${geoSorted.length} items`}>
        {geoSorted.length === 0 ? (
          <p className={`${GLASS} p-5 text-sm text-muted-foreground`}>
            No GEO recommendations are stored in this report yet. Run a new audit from the dashboard.
          </p>
        ) : (
          <motion.div
            initial={reduce ? "show" : "hidden"}
            whileInView="show"
            viewport={{ once: true, amount: 0.1 }}
            variants={sectionContainer}
            className="grid grid-cols-1 gap-5 lg:grid-cols-2"
          >
            {geoSorted.map((rec, i) => (
              <RecCard key={`geo-${rec.title}-${i}`} rec={rec} />
            ))}
          </motion.div>
        )}
      </Section>
    </>
  );
}
