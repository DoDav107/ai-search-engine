import { spawnSync } from "node:child_process";

import { getRepoRoot, getVenvPython } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Normalise a user-typed site URL via the SHARED Python normaliser (src.engine.url_utils),
// so the form's "Auditing: <clean url>" preview is byte-for-byte what the crawler receives
// (no drift between surfaces). Returns { url } on success or { error } on invalid input.
export async function GET(request: Request) {
  const raw = new URL(request.url).searchParams.get("url") ?? "";
  if (!raw.trim()) {
    return Response.json({ error: "Enter a website URL or domain, e.g. nandos.com.au" }, { status: 200 });
  }
  const repoRoot = getRepoRoot();
  const python = getVenvPython(repoRoot);
  const result = spawnSync(python, ["-m", "src.engine.url_utils", raw], {
    cwd: repoRoot,
    encoding: "utf-8",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  try {
    return Response.json(JSON.parse(result.stdout || "{}"), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: result.stderr?.trim() || "Could not parse the URL." }, { status: 200 });
  }
}
