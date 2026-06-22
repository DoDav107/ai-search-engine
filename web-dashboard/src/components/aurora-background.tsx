// Animated gradient backdrop. Pure CSS so it stays a Server Component; the drift
// animation is gated by `prefers-reduced-motion` in globals.css.
export function AuroraBackground() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-background"
    >
      {/* base radial wash */}
      <div className="absolute inset-0 bg-[radial-gradient(125%_125%_at_50%_-10%,#0e1730_0%,#070a12_55%)]" />

      {/* drifting colour blobs (blue data + amber highlight + violet depth) */}
      <div className="aurora-blob aurora-blob-1 absolute -top-40 -left-32 h-[38rem] w-[38rem] rounded-full bg-[#1d4ed8]/30 blur-[130px]" />
      <div className="aurora-blob aurora-blob-2 absolute top-1/3 -right-32 h-[34rem] w-[34rem] rounded-full bg-[#f59e0b]/15 blur-[130px]" />
      <div className="aurora-blob aurora-blob-1 absolute -bottom-40 left-1/3 h-[32rem] w-[32rem] rounded-full bg-[#7c3aed]/20 blur-[130px]" />

      {/* subtle data grid, faded toward the edges */}
      <div className="absolute inset-0 opacity-[0.15] [background-image:linear-gradient(rgba(255,255,255,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.06)_1px,transparent_1px)] [background-size:48px_48px] [mask-image:radial-gradient(ellipse_at_center,black_25%,transparent_75%)]" />
    </div>
  );
}
