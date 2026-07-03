"use client";

import { useCallback, useEffect, useState } from "react";
import { motion, useReducedMotion, type Variants } from "framer-motion";
import { Activity, Search, Bot } from "lucide-react";
import { ScoreCard } from "./score-card";
import { SeoSection } from "./seo-section";
import { GeoSection } from "./geo-section";
import { RecommendationsSection } from "./recommendations-section";
import { TrendsSection } from "./trends-section";
import { ExportButton } from "./export-button";
import { PrintButton } from "./print-button";
import { NewAudit } from "./new-audit";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { GLASS, type Report } from "@/lib/report";

const container: Variants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.12, delayChildren: 0.1 },
  },
};

const item: Variants = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] } },
};

function formatTimestamp(iso?: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

export function Dashboard() {
  const reduce = useReducedMotion();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Selected report tab. Lives here (not reset on report re-fetch/re-run) so switching
  // tabs and completing a New Audit keep the user on their chosen tab.
  const [tab, setTab] = useState("overview");

  // Reusable so the "New Audit" flow can reload the dashboard on completion.
  const loadReport = useCallback(() => {
    setLoading(true);
    fetch("/api/report", { cache: "no-store" })
      .then((r) => r.json())
      .then((data: Report) => {
        if (data.error) {
          setError(data.error);
          setReport(null);
        } else {
          setError(null);
          setReport(data);
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const id = window.setTimeout(loadReport, 0);
    return () => window.clearTimeout(id);
  }, [loadReport]);

  const generated = report ? formatTimestamp(report._generated_at) : null;
  const initial = reduce ? "show" : "hidden";

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-12 sm:py-16">
      {/* New Audit — always available, even before any report exists. */}
      <div className="mb-8 flex justify-end print:hidden">
        <NewAudit onComplete={loadReport} />
      </div>

      {!report && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-6 py-5 text-sm text-muted-foreground">
          {loading ? (
            <span className="flex items-center gap-3">
              <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary" />
              <span className="font-mono">Loading latest report…</span>
            </span>
          ) : (
            <span>
              {error ?? "No report yet."} Start one with <strong>New Audit</strong> above.
            </span>
          )}
        </div>
      )}

      {report && (
        <>
          {/* Hero header */}
          <motion.header
            initial={initial}
            animate="show"
            variants={container}
            className="mb-10 sm:mb-14"
          >
            <motion.div
              variants={item}
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-medium text-muted-foreground backdrop-blur-md"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-success" />
              AI-Powered Audit
            </motion.div>

            <motion.h1
              variants={item}
              className="mt-4 text-4xl font-semibold tracking-tight sm:text-6xl"
            >
              <span className="bg-gradient-to-r from-white via-white to-primary bg-clip-text text-transparent">
                {report.brand ?? "Site"}
              </span>
            </motion.h1>

            <motion.p
              variants={item}
              className="mt-2 text-lg text-muted-foreground sm:text-xl"
            >
              SEO &amp; GEO Audit
            </motion.p>

            <motion.div variants={item} className="mt-4 flex flex-wrap items-center gap-4">
              {generated && (
                <p className="font-mono text-xs text-muted-foreground/70">
                  Generated {generated}
                </p>
              )}
              {report.client && (
                <p className="font-mono text-xs text-muted-foreground/70">
                  Client {report.client}
                </p>
              )}
              <ExportButton report={report} />
              <PrintButton />
            </motion.div>
          </motion.header>

          {/* Tabbed report — same data (fetched once), grouped so users don't scroll
              through everything. Tab selection persists across re-runs (state above). */}
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="mb-8 print:hidden">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="seo">SEO</TabsTrigger>
              <TabsTrigger value="geo">GEO</TabsTrigger>
              <TabsTrigger value="trends">Trends</TabsTrigger>
            </TabsList>

            <TabsContent value="overview">
              <motion.section
                initial={initial}
                animate="show"
                variants={container}
                className="grid grid-cols-1 gap-5 sm:gap-6 md:grid-cols-3"
                aria-label="Overall scores"
              >
                <ScoreCard label="Unified Score" value={report.unified_score ?? 0} icon={Activity} featured />
                <ScoreCard label="SEO Score" value={report.seo_score ?? 0} icon={Search} />
                <ScoreCard label="GEO Score" value={report.geo_score ?? 0} icon={Bot} />
              </motion.section>

              {/* Assessments (grounded narratives) — surfaced up front on Overview. */}
              {(report.seo_assessment || report.geo_assessment) && (
                <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-2">
                  {report.seo_assessment && (
                    <div className={`${GLASS} p-5 sm:p-6`}>
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">SEO Assessment</p>
                      <p className="mt-2 text-sm leading-relaxed text-foreground/85">{report.seo_assessment}</p>
                    </div>
                  )}
                  {report.geo_assessment && (
                    <div className={`${GLASS} p-5 sm:p-6`}>
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">GEO Assessment</p>
                      <p className="mt-2 text-sm leading-relaxed text-foreground/85">{report.geo_assessment}</p>
                    </div>
                  )}
                </div>
              )}

              <RecommendationsSection report={report} only="top" />
            </TabsContent>

            <TabsContent value="seo">
              <SeoSection report={report} showAssessment={false} />
              <RecommendationsSection report={report} only="seo" />
            </TabsContent>

            <TabsContent value="geo">
              <GeoSection report={report} showAssessment={false} />
              <RecommendationsSection report={report} only="geo" />
            </TabsContent>

            <TabsContent value="trends">
              <TrendsSection defaultClient={report.client ?? report.brand} />
            </TabsContent>
          </Tabs>
        </>
      )}
    </main>
  );
}
