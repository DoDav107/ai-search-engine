import { spawnSync } from "node:child_process";

import { getRepoRoot, getVenvPython } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Opt-in "save provider key to server .env" (LOCAL/SINGLE-USER DEV ONLY). The write is
// performed by src.security.env_writer, which re-checks the gate (ALLOW_ENV_KEY_WRITE on
// AND HOSTED off), resolves provider→env var, validates the key belongs to the SELECTED
// provider (prefix + cheap auth ping), and writes atomically. The key is forwarded on
// STDIN (never argv) and is NEVER echoed back — the response carries only
// { provider, env_var, last4 }. Disabled → 403 (never trust the UI alone).
export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ ok: false, message: "Invalid JSON body." }, { status: 400 });
  }
  const source = (body ?? {}) as Record<string, unknown>;
  const provider = String(source.provider ?? "").trim().toLowerCase();
  const key = String(source.key ?? "");
  if (!provider || !key) {
    return Response.json({ ok: false, message: "provider and key are required." }, { status: 400 });
  }

  const repoRoot = getRepoRoot();
  const python = getVenvPython(repoRoot);
  const result = spawnSync(python, ["-m", "src.security.env_writer", "--provider", provider], {
    cwd: repoRoot,
    encoding: "utf-8",
    input: key, // key via stdin only — never argv/process list
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  let out: { ok?: boolean; message?: string; disabled?: boolean; provider?: string; env_var?: string; last4?: string };
  try {
    out = JSON.parse(result.stdout || "{}");
  } catch {
    out = { ok: false, message: result.stderr?.trim() || "Could not save the key." };
  }
  // Feature disabled server-side → 403; other refusals → 400; success → 200.
  // Response carries only { provider, env_var, last4 } — never the key.
  const status = out.ok ? 200 : out.disabled ? 403 : 400;
  return Response.json(out, { status, headers: { "Cache-Control": "no-store" } });
}
