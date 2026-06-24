"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Play, Plus, Rocket, X } from "lucide-react";

const MAX_QUERIES = 10;
const POLL_MS = 2000;

type ProgressEvent = { phase: string; [key: string]: unknown };
type Status = "idle" | "running" | "done" | "error";
type JobStatus = {
  jobId?: string;
  status?: Status;
  startedAt?: string;
  updatedAt?: string;
  finishedAt?: string;
  events?: ProgressEvent[];
  error?: string | null;
  stderr?: string | null;
};

const BTN =
  "inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-sm font-medium text-foreground backdrop-blur-md transition-colors hover:border-white/20 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50";

function normalizeDomain(domain: string): string {
  const value = domain.trim();
  return value && !value.includes("://") ? `https://${value}` : value;
}

function parseQueries(raw: string): string[] {
  return raw.split("\n").map((q) => q.trim()).filter(Boolean);
}

function validate(client: string, brand: string, domain: string, queries: string[]): string[] {
  const errors: string[] = [];
  if (!client.trim()) errors.push("Client is required.");
  if (!brand.trim()) errors.push("Brand / company name is required.");
  try {
    const u = new URL(normalizeDomain(domain));
    if (!(u.protocol === "http:" || u.protocol === "https:") || !u.hostname.includes(".")) {
      throw new Error("bad");
    }
  } catch {
    errors.push("Enter a valid domain or website URL (e.g. https://example.com).");
  }
  if (queries.length === 0) errors.push("Add at least one target query (one per line).");
  if (queries.length > MAX_QUERIES) {
    errors.push(`Too many queries (${queries.length}). The cap is ${MAX_QUERIES} — remove some.`);
  }
  return errors;
}

function formatEvent(ev: ProgressEvent): string {
  switch (ev.phase) {
    case "start":
      return "Starting audit.";
    case "queued":
      return "Preparing pipeline config.";
    case "crawl":
      return "Crawling site and scoring SEO.";
    case "crawl_done":
      return `SEO scored: ${ev.pages ?? "?"} page(s).`;
    case "geo_start":
      return `GEO measurement started: ${ev.total ?? "?"} queries.`;
    case "geo": {
      const browsed = ev.web_search_used ? "browsed" : "no browse";
      const err = ev.error ? " · error" : "";
      const q = String(ev.query ?? "").slice(0, 60);
      return `[GEO ${ev.index}/${ev.total}] ${q} - ${browsed}${err}`;
    }
    case "recommend":
      return "Building recommendations and draft fixes.";
    case "saving":
      return "Saving report, history, and PDF.";
    case "done":
      return "Audit complete.";
    case "error":
      return String(ev.message ?? "Audit failed.");
    default:
      return String(ev.message ?? ev.phase);
  }
}

export function NewAudit({ onComplete }: { onComplete: () => void }) {
  const [open, setOpen] = useState(false);
  const [client, setClient] = useState("");
  const [brand, setBrand] = useState("");
  const [domain, setDomain] = useState("");
  const [queriesRaw, setQueriesRaw] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [runError, setRunError] = useState<string | null>(null);
  const completedRef = useRef(false);

  const queries = parseQueries(queriesRaw);
  const running = status === "running";

  async function handleSubmit() {
    const errs = validate(client, brand, domain, queries);
    if (!confirm) errs.push("Tick the confirmation box before running.");
    setErrors(errs);
    if (errs.length) return;

    setRunError(null);
    setEvents([]);
    completedRef.current = false;
    try {
      const res = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client: client.trim(),
          brand: brand.trim(),
          domain: normalizeDomain(domain),
          queries,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setErrors(data.errors ?? ["Could not start the audit."]);
        return;
      }
      setJobId(data.jobId);
      setStatus("running");
    } catch (e) {
      setRunError(String(e));
      setStatus("error");
    }
  }

  // Poll status while running.
  useEffect(() => {
    if (!jobId || status !== "running") return;
    let cancelled = false;

    const tick = async () => {
      try {
        const res = await fetch(`/api/audit/${encodeURIComponent(jobId)}`, {
          cache: "no-store",
        });
        const data = (await res.json()) as JobStatus;
        if (cancelled) return;
        if (!res.ok) {
          setRunError(data.error ?? "Lost track of the audit job.");
          setStatus("error");
          return;
        }
        setEvents(data.events ?? []);
        const started = Date.parse(data.startedAt ?? "");
        const ended = Date.parse(data.finishedAt ?? data.updatedAt ?? new Date().toISOString());
        setElapsedMs(Number.isFinite(started) && Number.isFinite(ended) ? Math.max(0, ended - started) : 0);
        if (data.status === "done") {
          setStatus("done");
          if (!completedRef.current) {
            completedRef.current = true;
            onComplete(); // refresh the dashboard with the new report
          }
        } else if (data.status === "error") {
          const stderr = data.stderr?.trim();
          setRunError([data.error ?? "The audit failed.", stderr].filter(Boolean).join("\n\n"));
          setStatus("error");
        }
      } catch (e) {
        if (!cancelled) {
          setRunError(String(e));
          setStatus("error");
        }
      }
    };

    void tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [jobId, status, onComplete]);

  const reset = useCallback(() => {
    setStatus("idle");
    setJobId(null);
    setEvents([]);
    setRunError(null);
    setElapsedMs(0);
  }, []);

  const elapsedSec = Math.round(elapsedMs / 1000);

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className={BTN}>
        <Plus className="h-4 w-4" aria-hidden />
        New Audit
      </button>
    );
  }

  return (
    <div className="w-full rounded-3xl border border-white/10 bg-white/[0.04] p-5 backdrop-blur-xl sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <Rocket className="h-4 w-4 text-primary" aria-hidden /> New Audit
        </h3>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-lg p-1 text-muted-foreground hover:text-foreground"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {status !== "running" && (
        <>
          <p className="mb-4 text-xs text-muted-foreground">
            Run a fresh audit on your own brand and domain. Diagnose-and-recommend only — it never
            publishes or changes your site.
          </p>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-xs font-medium text-muted-foreground">Client</span>
              <input
                value={client}
                onChange={(e) => setClient(e.target.value)}
                placeholder="e.g. Acme Retail"
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm outline-none focus:border-primary/60"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-xs font-medium text-muted-foreground">
                Brand / company name
              </span>
              <input
                value={brand}
                onChange={(e) => setBrand(e.target.value)}
                placeholder="e.g. Acme Running"
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm outline-none focus:border-primary/60"
              />
            </label>
            <label className="text-sm sm:col-span-2">
              <span className="mb-1 block text-xs font-medium text-muted-foreground">Domain / website URL</span>
              <input
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="https://example.com"
                className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm outline-none focus:border-primary/60"
              />
            </label>
          </div>

          <label className="mt-4 block text-sm">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">
              Target queries (one per line)
            </span>
            <textarea
              value={queriesRaw}
              onChange={(e) => setQueriesRaw(e.target.value)}
              rows={5}
              placeholder={"What are the best running shoe brands?\nMost popular sneakers right now?"}
              className="w-full resize-y rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 font-mono text-xs outline-none focus:border-primary/60"
            />
            <span className="mt-1 block text-xs text-muted-foreground">
              {queries.length}/{MAX_QUERIES} queries · each runs a live web-search measurement (paid).
            </span>
          </label>

          <label className="mt-4 flex items-start gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
              className="mt-0.5"
            />
            <span>I understand this crawls the site and makes live, paid AI calls.</span>
          </label>

          {errors.length > 0 && (
            <ul className="mt-3 space-y-1">
              {errors.map((e) => (
                <li key={e} className="flex items-center gap-2 text-xs text-danger">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {e}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 flex items-center gap-3">
            <button type="button" onClick={handleSubmit} className={BTN}>
              <Play className="h-4 w-4" aria-hidden /> Run Audit
            </button>
            {status === "done" && (
              <span className="inline-flex items-center gap-1.5 text-xs text-success">
                <CheckCircle2 className="h-4 w-4" aria-hidden /> Complete — report updated below.
              </span>
            )}
            {status === "error" && (
              <button type="button" onClick={reset} className="text-xs text-muted-foreground underline">
                Reset
              </button>
            )}
          </div>
        </>
      )}

      {/* Running / progress state */}
      {(running || (events.length > 0 && status !== "idle")) && (
        <div className="mt-4 rounded-2xl border border-white/10 bg-black/20 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm">
            {running ? (
              <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
            ) : status === "done" ? (
              <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
            ) : (
              <AlertCircle className="h-4 w-4 text-danger" aria-hidden />
            )}
            <span className="font-medium">
              {running ? "Running audit…" : status === "done" ? "Audit complete" : "Audit failed"}
            </span>
            <span className="ml-auto font-mono text-xs text-muted-foreground">{elapsedSec}s elapsed</span>
          </div>
          <div className="max-h-48 space-y-1 overflow-y-auto font-mono text-[11px] leading-relaxed text-foreground/80">
            {events.slice(-14).map((ev, i) => (
              <div key={`${ev.phase}-${i}`}>{formatEvent(ev)}</div>
            ))}
            {running && events.length === 0 && <div>Waiting for the pipeline to start…</div>}
          </div>
          {runError && (
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-foreground/90">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="whitespace-pre-wrap">{runError}</span>
            </p>
          )}
          {status === "done" && (
            <p className="mt-3 text-xs text-success">The dashboard below now shows your new report.</p>
          )}
        </div>
      )}
    </div>
  );
}
