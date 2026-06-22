"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion, type Variants } from "framer-motion";
import { Activity, Search, Bot } from "lucide-react";
import { ScoreCard } from "./score-card";
import { SeoSection } from "./seo-section";
import { GeoSection } from "./geo-section";
import { RecommendationsSection } from "./recommendations-section";
import { ExportButton } from "./export-button";
import type { Report } from "@/lib/report";

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

  useEffect(() => {
    fetch("/api/report")
      .then((r) => r.json())
      .then((data: Report) => {
        if (data.error) setError(data.error);
        else setReport(data);
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-6xl items-center px-6">
        <div className="rounded-2xl border border-danger/30 bg-danger/10 px-6 py-5 text-sm text-foreground">
          {error}
        </div>
      </main>
    );
  }

  if (!report) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-6xl items-center justify-center px-6">
        <div className="flex items-center gap-3 text-muted-foreground">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary" />
          <span className="font-mono text-sm">Loading latest report…</span>
        </div>
      </main>
    );
  }

  const generated = formatTimestamp(report._generated_at);
  const initial = reduce ? "show" : "hidden";

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-12 sm:py-16">
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

        <motion.div variants={item} className="mt-4 flex items-center gap-4">
          {generated && (
            <p className="font-mono text-xs text-muted-foreground/70">
              Generated {generated}
            </p>
          )}
          <ExportButton report={report} />
        </motion.div>
      </motion.header>

      {/* Hero score cards */}
      <motion.section
        initial={initial}
        animate="show"
        variants={container}
        className="grid grid-cols-1 gap-5 sm:gap-6 md:grid-cols-3"
        aria-label="Overall scores"
      >
        <ScoreCard
          label="Unified Score"
          value={report.unified_score ?? 0}
          icon={Activity}
          featured
        />
        <ScoreCard label="SEO Score" value={report.seo_score ?? 0} icon={Search} />
        <ScoreCard label="GEO Score" value={report.geo_score ?? 0} icon={Bot} />
      </motion.section>

      {/* Data sections */}
      <SeoSection report={report} />
      <GeoSection report={report} />
      <RecommendationsSection report={report} />
    </main>
  );
}
