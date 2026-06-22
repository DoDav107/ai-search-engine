import { NextResponse } from "next/server";
import { readFile, stat } from "fs/promises";
import path from "path";

// Always read fresh from disk so the dashboard reflects the latest pipeline run.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  // The Python pipeline writes this file; web-dashboard/ sits next to data/.
  const reportPath = path.join(
    process.cwd(),
    "..",
    "data",
    "reports",
    "latest_report.json"
  );

  try {
    const [raw, info] = await Promise.all([
      readFile(reportPath, "utf-8"),
      stat(reportPath),
    ]);
    const data = JSON.parse(raw);
    // The pipeline doesn't embed a timestamp; use the report file's mtime as
    // the "generated at" time (no pipeline changes required).
    data._generated_at = info.mtime.toISOString();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    return NextResponse.json(
      {
        error:
          "Could not read latest_report.json — run `python -m src.pipeline` first.",
        path: reportPath,
        detail: String(err),
      },
      { status: 404 }
    );
  }
}
