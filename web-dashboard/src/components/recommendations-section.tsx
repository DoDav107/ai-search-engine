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
import { Section, sectionItem } from "./section";

// Recommendation items SHOULD be objects, but render defensively: a plain-string item or
// an object missing fields must still show its available text, never a blank card.
type RawRec = Recommendation | string;
const _KNOWN = new Set([
  "area", "title", "priority", "scope", "issue", "why_it_matters", "recommendation", "draft",
]);

function asRec(item: RawRec): Recommendation {
  if (typeof item === "string") {
    return { area: "", title: "", priority: "", scope: "", issue: "",
      why_it_matters: "", recommendation: item, draft: "" };
  }
  return item ?? ({ area: "", title: "", priority: "", scope: "", issue: "",
    why_it_matters: "", recommendation: "", draft: "" } as Recommendation);
}

// Any string value on the object that isn't one of the known fields — so an unexpected
// shape (e.g. {text: "..."}) still surfaces its text instead of rendering empty.
function extraText(rec: Recommendation): string {
  return Object.entries(rec as Record<string, unknown>)
    .filter(([k, v]) => !_KNOWN.has(k) && typeof v === "string" && v.trim())
    .map(([, v]) => String(v))
    .join(" · ");
}

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

// Self-contained mount animation (NOT whileInView/variants): the card always settles at
// opacity 1 on mount, so content can never be left stuck-hidden by viewport/propagation
// orchestration (the previous blank-card failure mode). reduce-motion → no animation.
function RecCard({ rec, index, reduce }: { rec: Recommendation; index: number; reduce: boolean }) {
  const fields: [string, string][] = (
    [
      ["Issue", rec.issue],
      ["Why it matters", rec.why_it_matters],
      ["Recommendation", rec.recommendation],
    ] as [string, string | undefined][]
  ).filter(([, v]) => !!(v && v.trim())) as [string, string][];

  const draft = (rec.draft ?? "").trim();
  const scope = (rec.scope ?? "").trim();
  const extra = extraText(rec);
  // Header text falls back through the available fields so it's never blank.
  const title =
    (rec.title || rec.recommendation || rec.issue || scope || extra || "Recommendation").trim();
  // If none of the structured fields/draft/scope rendered, surface any text we do have.
  const bodyEmpty = fields.length === 0 && !draft && !scope;

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: Math.min(index * 0.05, 0.3) }}
      className={`${GLASS} flex flex-col gap-4 p-5 sm:p-6`}
    >
      <div className="flex items-start justify-between gap-3">
        <h4 className="text-base font-semibold leading-snug text-foreground">{title}</h4>
        {rec.priority ? <PriorityBadge priority={rec.priority} /> : null}
      </div>
      {scope && <p className="-mt-2 text-xs text-muted-foreground">{scope}</p>}
      {fields.map(([label, value]) => (
        <Field key={label} label={label}>{value}</Field>
      ))}

      {draft && (
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Draft fix
            </p>
            <CopyButton text={draft} />
          </div>
          <pre className="max-h-64 overflow-auto rounded-xl border border-white/10 bg-black/30 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-foreground/85">
            {draft}
          </pre>
        </div>
      )}

      {/* Last-resort fallback so a sparse/unknown item never renders an empty card. */}
      {bodyEmpty && extra && <p className="text-sm leading-relaxed text-foreground/85">{extra}</p>}
    </motion.div>
  );
}

export function RecommendationsSection({ report }: { report: Report }) {
  const reduce = useReducedMotion() ?? false;
  // Normalise every item to a safe object up front (string item → object; missing fields
  // filled), so sorting and rendering never touch undefined fields.
  const seo = ((report.seo_recommendations ?? []) as RawRec[]).map(asRec);
  const geo = ((report.geo_recommendations ?? []) as RawRec[]).map(asRec);

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
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {seoSorted.map((rec, i) => (
              <RecCard key={`seo-${rec.title}-${i}`} rec={rec} index={i} reduce={reduce} />
            ))}
          </div>
        )}
      </Section>

      {/* GEO Recommendations */}
      <Section title="GEO Recommendations" subtitle={`${geoSorted.length} items`}>
        {geoSorted.length === 0 ? (
          <p className={`${GLASS} p-5 text-sm text-muted-foreground`}>
            No GEO recommendations are stored in this report yet. Run a new audit from the dashboard.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            {geoSorted.map((rec, i) => (
              <RecCard key={`geo-${rec.title}-${i}`} rec={rec} index={i} reduce={reduce} />
            ))}
          </div>
        )}
      </Section>
    </>
  );
}
