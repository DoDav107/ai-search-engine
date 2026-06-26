import { spawnSync } from "node:child_process";

import { getRepoRoot, getVenvPython } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const repoRoot = getRepoRoot();
  const python = getVenvPython(repoRoot);
  const result = spawnSync(python, ["-m", "src.reporting.geo_options"], {
    cwd: repoRoot,
    encoding: "utf-8",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  if (result.status !== 0) {
    return Response.json(
      { error: result.stderr.trim() || "Could not load GEO options." },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }

  return new Response(result.stdout, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}
