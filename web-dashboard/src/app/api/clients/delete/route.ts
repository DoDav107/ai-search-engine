import { spawnSync } from "node:child_process";

import { getRepoRoot, getVenvPython } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Destructive: removes ONE client's saved report history via the SAME shared Python action
// the Streamlit dashboard calls (src.reporting.delete_client -> history.delete_client). The
// client id is validated against the enumerated client list SERVER-SIDE (in Python), so a
// bogus/non-listed id is rejected and never interpolated into a path here.
export async function POST(request: Request) {
  let client = "";
  try {
    const body = await request.json();
    client = String(body?.client ?? "").trim();
  } catch {
    return Response.json({ error: "Invalid request body." }, { status: 400 });
  }
  if (!client) {
    return Response.json({ error: "A client is required." }, { status: 400 });
  }

  const repoRoot = getRepoRoot();
  const python = getVenvPython(repoRoot);
  const result = spawnSync(
    python,
    ["-m", "src.reporting.delete_client", "--client", client],
    { cwd: repoRoot, encoding: "utf-8", env: { ...process.env, PYTHONUNBUFFERED: "1" } },
  );

  // exit 2 = rejected (unknown client) with a JSON body; other non-zero = failure.
  if (result.status !== 0) {
    let message = result.stderr?.trim() || "Could not remove the client.";
    try {
      const parsed = JSON.parse(result.stdout || "{}");
      if (parsed?.error) message = parsed.error;
    } catch {
      /* stderr already captured */
    }
    return Response.json(
      { error: message },
      { status: result.status === 2 ? 400 : 500, headers: { "Cache-Control": "no-store" } },
    );
  }

  return new Response(result.stdout, {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
