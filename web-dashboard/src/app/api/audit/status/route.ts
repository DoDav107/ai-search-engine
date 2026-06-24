import { readJob } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const jobId = new URL(request.url).searchParams.get("job_id") ?? "";

  try {
    const job = readJob(jobId);
    if (!job) {
      return Response.json({ error: "Unknown audit job." }, { status: 404 });
    }

    return Response.json(
      {
        ...job,
        job_id: job.jobId,
        elapsed_ms: Date.parse(job.finishedAt ?? job.updatedAt) - Date.parse(job.startedAt),
        report_ready: job.status === "done",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }
}
