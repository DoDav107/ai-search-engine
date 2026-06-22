"use client";

import { Download } from "lucide-react";
import type { Report } from "@/lib/report";

// Downloads the full report as JSON (client-side blob — no extra request).
export function ExportButton({ report }: { report: Report }) {
  function handleExport() {
    const { _generated_at: _omit, ...clean } = report;
    const blob = new Blob([JSON.stringify(clean, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const brand = (report.brand ?? "report").toLowerCase().replace(/[^a-z0-9]+/g, "-");
    a.href = url;
    a.download = `${brand}-audit-report.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <button
      type="button"
      onClick={handleExport}
      className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-sm font-medium text-foreground backdrop-blur-md transition-colors hover:border-white/20 hover:bg-white/[0.08]"
    >
      <Download className="h-4 w-4" aria-hidden />
      Export JSON
    </button>
  );
}
