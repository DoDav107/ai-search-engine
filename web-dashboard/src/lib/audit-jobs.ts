import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const STDERR_LIMIT = 12_000;
const MAX_EVENTS = 200;

// API-key env var per provider — mirrors PROVIDER_ENV_VAR in src/agents/geo_agent.py.
// Lets a temporary key be injected for the SELECTED provider (not just OpenAI).
const PROVIDER_ENV_VAR: Record<string, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  google: "GOOGLE_API_KEY",
  xai: "XAI_API_KEY",
  perplexity: "PERPLEXITY_API_KEY",
  deepseek: "DEEPSEEK_API_KEY",
};

function temporaryKeyEnv(input: AuditInput): Record<string, string> {
  if (input.api_key_mode !== "temporary" || !input.temporary_api_key) return {};
  const envVar = PROVIDER_ENV_VAR[(input.geo_provider ?? "").toLowerCase()];
  return envVar ? { [envVar]: input.temporary_api_key } : {};
}

export type ProgressEvent = { phase: string; [key: string]: unknown };

export type AuditInput = {
  client: string;
  brand: string;
  domain: string;
  queries: string[];
  geo_provider?: string;
  geo_model?: string;
  api_key_mode?: "env" | "temporary";
  temporary_api_key?: string;
};

export type AuditJob = {
  jobId: string;
  status: "running" | "done" | "error";
  client: string;
  brand: string;
  domain: string;
  queries: string[];
  geo_provider?: string;
  geo_model?: string;
  api_key_source?: "env" | "temporary" | "none";
  startedAt: string;
  updatedAt: string;
  finishedAt?: string;
  pid?: number;
  events: ProgressEvent[];
  stderr?: string;
  error?: string;
  config?: {
    crawl: string;
    geo: string;
  };
};

type ConfigPaths = { crawl: string; geo: string };

function hasRepoMarkers(dir: string): boolean {
  return (
    fs.existsSync(path.join(dir, "src", "pipeline.py")) &&
    fs.existsSync(path.join(dir, "web-dashboard", "package.json"))
  );
}

export function getRepoRoot(): string {
  const cwd = process.cwd();
  const candidates = [
    path.resolve(cwd, ".."),
    cwd,
    path.resolve(cwd, "../.."),
  ];
  const repoRoot = candidates.find(hasRepoMarkers);
  if (!repoRoot) {
    throw new Error(`Could not resolve repo root from ${cwd}`);
  }
  return repoRoot;
}

export function getVenvPython(repoRoot = getRepoRoot()): string {
  const python = path.join(repoRoot, ".venv", "bin", "python");
  if (!fs.existsSync(python)) {
    throw new Error(`Could not find pipeline Python at ${python}`);
  }
  return python;
}

function jobsDir(repoRoot = getRepoRoot()): string {
  return path.join(repoRoot, "data", "jobs");
}

function jobPath(jobId: string, repoRoot = getRepoRoot()): string {
  if (!/^[a-f0-9-]{36}$/i.test(jobId)) {
    throw new Error("Invalid jobId.");
  }
  return path.join(jobsDir(repoRoot), `${jobId}.json`);
}

function writeJsonAtomic(filePath: string, data: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmpPath, `${JSON.stringify(data, null, 2)}\n`, "utf-8");
  fs.renameSync(tmpPath, filePath);
}

function persistJob(job: AuditJob, repoRoot = getRepoRoot()): void {
  writeJsonAtomic(jobPath(job.jobId, repoRoot), job);
}

function tail(value: string): string {
  return value.length > STDERR_LIMIT ? value.slice(-STDERR_LIMIT) : value;
}

function appendEvent(job: AuditJob, event: ProgressEvent, repoRoot: string): void {
  job.events = [...job.events, event].slice(-MAX_EVENTS);
  job.updatedAt = new Date().toISOString();
  persistJob(job, repoRoot);
}

function runConfigWriter(
  python: string,
  repoRoot: string,
  input: AuditInput,
  config: ConfigPaths,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      python,
      ["-m", "src.reporting.audit_config", "--crawl-out", config.crawl, "--geo-out", config.geo],
      {
        cwd: repoRoot,
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        stdio: ["pipe", "ignore", "pipe"],
      },
    );

    let stderr = "";
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr = tail(stderr + chunk.toString());
    });
    child.on("error", (error) => reject(error));
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(stderr.trim() || `Config writer exited with code ${code}`));
    });
    child.stdin?.end(JSON.stringify(input));
  });
}

async function writeAuditConfigs(
  input: AuditInput,
  jobId: string,
  repoRoot: string,
  python: string,
): Promise<ConfigPaths> {
  const configDir = path.join(jobsDir(repoRoot), "configs", jobId);
  const config = {
    crawl: path.join(configDir, "crawl_config.yaml"),
    geo: path.join(configDir, "geo_config.yaml"),
  };
  const safeInput: AuditInput = { ...input };
  delete safeInput.temporary_api_key;
  await runConfigWriter(python, repoRoot, safeInput, config);
  return config;
}

export async function startAudit(input: AuditInput): Promise<AuditJob> {
  const repoRoot = getRepoRoot();
  const python = getVenvPython(repoRoot);
  const now = new Date().toISOString();
  const job: AuditJob = {
    jobId: randomUUID(),
    status: "running",
    client: input.client,
    brand: input.brand,
    domain: input.domain,
    queries: input.queries,
    geo_provider: input.geo_provider,
    geo_model: input.geo_model,
    api_key_source: input.api_key_mode === "temporary" ? "temporary" : input.geo_provider === "mock" ? "none" : "env",
    startedAt: now,
    updatedAt: now,
    events: [{ phase: "queued", message: "Preparing pipeline config." }],
  };

  persistJob(job, repoRoot);

  try {
    job.config = await writeAuditConfigs(input, job.jobId, repoRoot, python);
    job.events.push({ phase: "start", message: "Launching Python pipeline." });
    job.updatedAt = new Date().toISOString();
    persistJob(job, repoRoot);
  } catch (error) {
    job.status = "error";
    job.error = error instanceof Error ? error.message : String(error);
    job.finishedAt = new Date().toISOString();
    job.updatedAt = job.finishedAt;
    persistJob(job, repoRoot);
    throw error;
  }

  const child = spawn(python, ["-m", "src.pipeline"], {
    cwd: repoRoot,
    detached: true,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      AUDIT_CRAWL_CONFIG_PATH: job.config.crawl,
      AUDIT_GEO_CONFIG_PATH: job.config.geo,
      AUDIT_PROGRESS_STDOUT: "1",
      ...temporaryKeyEnv(input),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  job.pid = child.pid;
  persistJob(job, repoRoot);

  let stdoutBuffer = "";
  child.stdout?.on("data", (chunk: Buffer) => {
    stdoutBuffer += chunk.toString();
    let newline = stdoutBuffer.indexOf("\n");
    while (newline >= 0) {
      const line = stdoutBuffer.slice(0, newline).trim();
      stdoutBuffer = stdoutBuffer.slice(newline + 1);
      if (line) {
        try {
          appendEvent(job, JSON.parse(line) as ProgressEvent, repoRoot);
        } catch {
          // The pipeline also prints human-readable summaries; only JSON lines are progress events.
        }
      }
      newline = stdoutBuffer.indexOf("\n");
    }
  });

  child.stderr?.on("data", (chunk: Buffer) => {
    job.stderr = tail((job.stderr ?? "") + chunk.toString());
    job.updatedAt = new Date().toISOString();
    persistJob(job, repoRoot);
  });

  child.on("error", (error) => {
    job.status = "error";
    job.error = `Failed to start pipeline: ${error.message}`;
    job.finishedAt = new Date().toISOString();
    job.updatedAt = job.finishedAt;
    persistJob(job, repoRoot);
  });

  child.on("close", (code, signal) => {
    if (job.status !== "error") {
      job.status = code === 0 ? "done" : "error";
      if (job.status === "error") {
        job.error = (job.stderr ?? "").trim() || `Pipeline exited with code ${code ?? signal}`;
      }
    }
    job.finishedAt = new Date().toISOString();
    job.updatedAt = job.finishedAt;
    persistJob(job, repoRoot);
  });

  child.unref();
  return job;
}

export function readJob(jobId: string): AuditJob | null {
  const repoRoot = getRepoRoot();
  try {
    return JSON.parse(fs.readFileSync(jobPath(jobId, repoRoot), "utf-8")) as AuditJob;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return null;
    }
    throw error;
  }
}
