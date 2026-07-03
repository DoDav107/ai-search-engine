"use client";

import { Printer } from "lucide-react";

const BTN =
  "inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-sm font-medium text-foreground backdrop-blur-md transition-colors hover:border-white/20 hover:bg-white/[0.08]";

// Lightweight, per-tab browser print / Save-as-PDF. This is a convenience that prints the
// CURRENTLY ACTIVE report tab — the inactive tab panels are display:none (see TabsContent),
// so window.print() naturally scopes to the visible tab. The @media print rules in
// globals.css hide the app chrome and flip to a legible light theme. This does NOT replace
// the pipeline-built full report at /api/report/pdf (kept alongside via ExportButton).
export function PrintButton() {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className={`${BTN} print:hidden`}
      title="Print or save the current tab as a PDF"
    >
      <Printer className="h-4 w-4" aria-hidden />
      Print / Save as PDF
    </button>
  );
}
