import { spawnSync } from "node:child_process";

import { getRepoRoot, getVenvPython } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Opt-in "save key to server .env" (LOCAL/TRUSTED USE ONLY). The actual write is done by
// src.reporting.env_key, which is gated behind ALLOW_ENV_KEY_WRITE and validates the
// provider + key. The key is forwarded on STDIN (never argv) and is NEVER echoed back in
// the response — only a {ok, env_var, message} status. Must stay disabled on public/
// multi-user deployments.
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
  const result = spawnSync(python, ["-m", "src.reporting.env_key", "--provider", provider], {
    cwd: repoRoot,
    encoding: "utf-8",
    input: key, // key via stdin only — never argv/process list
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  let out: { ok?: boolean; message?: string; env_var?: string };
  try {
    out = JSON.parse(result.stdout || "{}");
  } catch {
    out = { ok: false, message: result.stderr?.trim() || "Could not save the key." };
  }
  // The response carries only a status — never the key.
  return Response.json(out, {
    status: out.ok ? 200 : 400,
    headers: { "Cache-Control": "no-store" },
  });
}
