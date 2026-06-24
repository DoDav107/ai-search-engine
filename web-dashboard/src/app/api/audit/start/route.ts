import { startAudit, type AuditInput } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_QUERIES = 10;

type Validation = { ok: true; data: AuditInput } | { ok: false; errors: string[] };

function normalizeUrl(value: string): string {
  const trimmed = value.trim();
  return trimmed && !trimmed.includes("://") ? `https://${trimmed}` : trimmed;
}

function validate(body: unknown): Validation {
  const source = (body ?? {}) as Record<string, unknown>;
  const brand = String(source.brand ?? "").trim();
  const client = String(source.client ?? brand).trim();
  const domain = normalizeUrl(String(source.domain ?? source.url ?? ""));
  const queries = (
    Array.isArray(source.queries)
      ? source.queries.map((query) => String(query))
      : String(source.queries ?? "").split("\n")
  )
    .map((query) => query.trim())
    .filter(Boolean);
  const errors: string[] = [];

  if (!client) errors.push("Client is required.");
  if (!brand) errors.push("Brand / company name is required.");
  try {
    const parsed = new URL(domain);
    if (!(parsed.protocol === "http:" || parsed.protocol === "https:") || !parsed.hostname.includes(".")) {
      throw new Error("Invalid URL");
    }
  } catch {
    errors.push("Enter a valid domain or website URL (e.g. https://example.com).");
  }
  if (queries.length === 0) errors.push("Add at least one target query.");
  if (queries.length > MAX_QUERIES) {
    errors.push(`Too many queries (${queries.length}). The cap is ${MAX_QUERIES}.`);
  }

  if (errors.length) return { ok: false, errors };
  return { ok: true, data: { client, brand, domain, queries } };
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ errors: ["Invalid JSON body."] }, { status: 400 });
  }

  const validation = validate(body);
  if (!validation.ok) {
    return Response.json({ errors: validation.errors }, { status: 400 });
  }

  try {
    const job = await startAudit(validation.data);
    return Response.json(
      { job_id: job.jobId, jobId: job.jobId, status: job.status },
      { status: 202, headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return Response.json(
      { errors: [error instanceof Error ? error.message : String(error)] },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }
}
