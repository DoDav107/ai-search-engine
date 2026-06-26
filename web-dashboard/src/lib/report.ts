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
  error?: string | null;
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
  // Which AI engine/model produced this answer (optional — absent on older reports).
  provider?: string;
  model?: string;
  // GEO quality signals (optional — absent on older reports; render as "unknown"/"N/A").
  sentiment_label?: "positive" | "neutral" | "negative" | "unknown" | string;
  sentiment_score?: number;
  recommendation_strength?: "strong" | "moderate" | "weak" | "none" | "unknown" | string;
  recommendation_score?: number;
  brand_rank_position?: number | null;
  competitor_count?: number;
  competitor_names_mentioned?: string[];
  citation_count?: number;
  citations_present?: boolean;
  answer_accuracy_label?: "accurate" | "partially_accurate" | "inaccurate" | "unknown" | string;
  answer_accuracy_notes?: string | null;
  per_query_geo_score?: number | null;
  web_grounded?: boolean;
  sources_count?: number;
  // Locale grounding applied to this query's search (optional — absent on older reports).
  // locale_applied: ISO country code (e.g. "AU") or "global"; locale_method: how it was applied.
  locale_applied?: string;
  locale_method?: "native_param" | "query_suffix" | "none" | string;
};

// Per engine/model GEO breakdown. Visibility differs across ChatGPT, Claude, etc.
// Per-engine GEO quality aggregates with EXPLICIT denominators (computed in Python so
// both dashboards render identical math/labels). Optional — absent on older reports.
export type CompetitorCount = { name: string; count: number };
export type CompetitorLeader = {
  name: string;
  mentions: number;
  sentiment_label: string;
  recommendation_strength: string;
  rank: number | null;
};
export type EngineQuality = {
  answers_total: number;
  brand_mentions: number;
  sov: number; // 0..1, brand-mention answers / all answers
  sentiment: {
    avg: number | null; // null when brand not mentioned
    positive: number;
    neutral: number;
    negative: number;
  };
  recommendation: { avg: number | null; strong?: number; moderate?: number; weak?: number };
  avg_brand_rank: number | null;
  citations_answers: number; // across ALL answers
  citation_coverage: number; // 0..1, across ALL answers
  competitor_total: number; // across ALL answers
  top_competitors: CompetitorCount[];
  competitor_leaders: CompetitorLeader[]; // zero-visibility pivot
};

export type EngineScore = {
  provider: string;
  model: string;
  geo_score: number;
  visibility_rate: number; // 0..1
  queries_run: number;
  brand_mentions?: number;
  avg_prominence?: number;
  api_key_source?: "env" | "temporary" | "none" | string;
  web_grounded?: boolean;
  sources_count?: number;
  grounding_warning?: string | null;
  quality?: EngineQuality | null;
  error?: string | null;
};

export type ShareOfVoice = {
  brand: string;
  is_subject: boolean;
  queries_present: number;
  share: number; // 0..1
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
  client?: string;
  seo_report?: { site_name?: string; score?: number; pages: PageReport[] };
  geo_report?: {
    brand?: string;
    engine?: string;
    geo_score?: number;
    results: GeoResult[];
    competitors_summary?: { name: string; query_count: number }[];
    share_of_voice?: ShareOfVoice[];
    sov_headline?: string;
    engine_scores?: EngineScore[];
  };
  seo_recommendations?: Recommendation[];
  geo_recommendations?: Recommendation[];
  geo_assessment?: string;
  audit_settings?: {
    client?: string;
    brand?: string;
    domain?: string;
    geo_provider?: string;
    geo_model?: string;
    api_key_source?: "env" | "temporary" | "none" | string;
    queries_count?: number;
  };
  _generated_at?: string;
  error?: string;
};

// ----- Trends over time (served by /api/trends → src.reporting.trends) -----
export type TrendRun = {
  timestamp: string; // ISO 8601
  unified: number | null;
  seo: number | null;
  geo: number | null;
  brand_visibility: number | null;
  subject_sov: number | null;
  // True when this run's gap to the PREVIOUS run is below the noise-guard threshold.
  low_confidence: boolean;
};
export type TrendSovSeries = { name: string; is_subject: boolean; values: (number | null)[] };
export type TrendQueryPoint = { prominence: number | null; mentioned: boolean };
export type TrendsSeries = {
  client: string;
  subject_name: string;
  min_interval_hours: number;
  enough_data: boolean;
  runs: TrendRun[];
  sov: TrendSovSeries[];
  queries: string[];
  query_series: Record<string, TrendQueryPoint[]>;
};
export type TrendsClients = { clients: string[]; min_interval_hours: number };

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
  crawl_access: "Crawl access",
  audit_coverage: "Audit coverage",
  https_enabled: "HTTPS",
  domain_brand_signal: "Brand/domain signal",
  canonical_url_shape: "Canonical URL shape",
};

export function factorLabel(id: string): string {
  return FACTOR_LABELS[id] ?? id;
}
