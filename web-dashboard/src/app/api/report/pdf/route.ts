import { readFile } from "fs/promises";
import path from "path";

// Serve the branded PDF the Python pipeline writes (data/reports/latest_report.pdf).
// Read fresh from disk each request so it reflects the latest run.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  // web-dashboard/ sits next to data/ at the repo root.
  const pdfPath = path.join(
    process.cwd(),
    "..",
    "data",
    "reports",
    "latest_report.pdf"
  );

  try {
    const buf = await readFile(pdfPath);
    return new Response(new Uint8Array(buf), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="audit-report.pdf"',
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return new Response(
      "PDF not found — run `python -m src.pipeline` (or `python -m src.reporting.pdf_report`) to generate it.",
      { status: 404, headers: { "Content-Type": "text/plain" } }
    );
  }
}
