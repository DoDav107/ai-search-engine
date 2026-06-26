import { spawnSync } from "node:child_process";

import { getRepoRoot, getVenvPython } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Trends-over-time series from saved report history. Reuses the SAME store + formulas as
// the Streamlit view via src.reporting.trends (no separate store, no rescoring):
//   GET /api/trends                          -> { clients: [...] }
//   GET /api/trends?client=adidas            -> full time series for that client
//   &minIntervalHours=12                     -> override the noise-guard threshold
export async function GET(request: Request) {
  const url = new URL(request.url);
  const client = (url.searchParams.get("client") || "").trim();
  const minIntervalHours = (url.searchParams.get("minIntervalHours") || "").trim();

  const repoRoot = getRepoRoot();
  const python = getVenvPython(repoRoot);
  const args = ["-m", "src.reporting.trends"];
  if (client) args.push("--client", client);
  if (minIntervalHours) args.push("--min-interval-hours", minIntervalHours);

  const result = spawnSync(python, args, {
    cwd: repoRoot,
    encoding: "utf-8",
    maxBuffer: 32 * 1024 * 1024,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  if (result.status !== 0) {
    return Response.json(
      { error: result.stderr?.trim() || "Could not load trends." },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }

  return new Response(result.stdout, {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
