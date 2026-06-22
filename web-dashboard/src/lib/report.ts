// Types + shared helpers for the audit report (shape mirrors latest_report.json).

export type FactorStatus = "pass" | "warn" | "fail" | string;

export type FactorResult = {
  id: string;
  status: FactorStatus;
  value: unknown;
  message: string;
};

export type PageReport = {
  url: string;
  factors: FactorResult[];
  score: number;
};

export type GeoResult = {
  query: string;
  engine: string;
  answer: string;
  error: string | null;
  brand_mentioned: boolean;
  mention_count: number;
  first_position: number | null;
  competitors_found: string[];
};

export type Priority = "High" | "Medium" | "Low" | string;

export type Recommendation = {
  area: string;
  title: string;
  priority: Priority;
  scope: string;
  issue: string;
  why_it_matters: string;
  recommendation: string;
  draft?: string;
};

export type Report = {
  site_name?: string;
  brand?: string;
  seo_score?: number;
  geo_score?: number;
  unified_score?: number;
  seo_report?: { site_name?: string; score?: number; pages: PageReport[] };
  geo_report?: { brand?: string; engine?: string; geo_score?: number; results: GeoResult[] };
  seo_recommendations?: Recommendation[];
  geo_recommendations?: Recommendation[];
  geo_assessment?: string;
  _generated_at?: string;
  error?: string;
};

// Shared glassmorphism card surface (matches 2A score cards).
// Surface and border lifted slightly so cards separate clearly from the dark base.
export const GLASS =
  "rounded-3xl border border-white/15 bg-white/[0.06] backdrop-blur-xl shadow-[0_8px_40px_-12px_rgba(0,0,0,0.6)]";

// Score band → colour + label (same thresholds as the score cards).
export function band(score: number): { color: string; label: string } {
  if (score >= 80) return { color: "var(--color-success)", label: "Strong" };
  if (score >= 50) return { color: "var(--color-warning)", label: "Needs work" };
  return { color: "var(--color-danger)", label: "Critical" };
}

export const PRIORITY_RANK: Record<string, number> = { High: 0, Medium: 1, Low: 2 };

export function priorityColor(priority: string): string {
  if (priority === "High") return "var(--color-danger)";
  if (priority === "Medium") return "var(--color-warning)";
  return "var(--color-brand)";
}

export function sortByPriority<T extends { priority: string }>(items: T[]): T[] {
  return [...items].sort(
    (a, b) => (PRIORITY_RANK[a.priority] ?? 1) - (PRIORITY_RANK[b.priority] ?? 1)
  );
}

// A GEO query has "no answer" when it errored OR returned empty text — never a miss.
export function isNoAnswer(r: GeoResult): boolean {
  return Boolean(r.error) || !(r.answer || "").trim();
}

// Prominence as a 0–100 percentage (how early the brand appears in the answer).
export function prominence(r: GeoResult): number | null {
  if (isNoAnswer(r) || !r.brand_mentioned || r.first_position === null) return null;
  const len = (r.answer || "").length;
  if (len <= 0) return null;
  const pct = (1 - r.first_position / len) * 100;
  return Math.max(0, Math.min(100, Math.round(pct * 10) / 10));
}

const FACTOR_LABELS: Record<string, string> = {
  title: "Title",
  meta_description: "Meta description",
  h1: "H1",
  canonical: "Canonical",
  image_alt: "Image ALT",
  word_count: "Word count",
  structured_data: "Structured data",
};

export function factorLabel(id: string): string {
  return FACTOR_LABELS[id] ?? id;
}
