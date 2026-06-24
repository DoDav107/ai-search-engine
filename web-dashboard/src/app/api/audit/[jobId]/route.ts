import { readJob } from "@/lib/audit-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = Promise<{ jobId: string }>;

export async function GET(_request: Request, context: { params: Params }) {
  const { jobId } = await context.params;

  try {
    const job = readJob(jobId);
    if (!job) {
      return Response.json({ error: "Unknown audit job." }, { status: 404 });
    }

    return Response.json(job, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }
}
