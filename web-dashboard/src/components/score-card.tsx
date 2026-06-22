"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { AnimatedNumber } from "./animated-number";

type Props = {
  label: string;
  value: number;
  icon: LucideIcon;
  featured?: boolean;
};

// Score band → colour + label (mirrors the analytics rating thresholds).
function band(score: number): { color: string; label: string } {
  if (score >= 80) return { color: "var(--color-success)", label: "Strong" };
  if (score >= 50) return { color: "var(--color-warning)", label: "Needs work" };
  return { color: "var(--color-danger)", label: "Critical" };
}

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] },
  },
};

const RADIUS = 54;
const CIRC = 2 * Math.PI * RADIUS;

export function ScoreCard({ label, value, icon: Icon, featured = false }: Props) {
  const reduce = useReducedMotion();
  const b = band(value);
  const pct = Math.max(0, Math.min(100, value)) / 100;
  const targetOffset = CIRC * (1 - pct);

  return (
    <motion.div
      variants={cardVariants}
      className={[
        "group relative overflow-hidden rounded-3xl border border-white/10 p-6 sm:p-7",
        "bg-white/[0.04] backdrop-blur-xl",
        "shadow-[0_8px_40px_-12px_rgba(0,0,0,0.6)]",
        "transition-colors duration-300 hover:border-white/20",
        featured ? "ring-1 ring-primary/30" : "",
      ].join(" ")}
    >
      {/* top-edge highlight for glass depth */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent" />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04]"
            style={{ color: b.color }}
          >
            <Icon className="h-5 w-5" strokeWidth={2} aria-hidden />
          </span>
          <span className="text-sm font-medium text-muted-foreground">
            {label}
          </span>
        </div>
        <span
          className="rounded-full border px-2.5 py-0.5 text-xs font-medium"
          style={{
            color: b.color,
            borderColor: `color-mix(in srgb, ${b.color} 40%, transparent)`,
            backgroundColor: `color-mix(in srgb, ${b.color} 12%, transparent)`,
          }}
        >
          {b.label}
        </span>
      </div>

      {/* gauge ring with centred count-up */}
      <div className="mt-6 flex items-center justify-center">
        <div className="relative h-40 w-40">
          <svg className="h-full w-full -rotate-90" viewBox="0 0 128 128">
            <circle
              cx="64"
              cy="64"
              r={RADIUS}
              fill="none"
              stroke="rgba(255,255,255,0.08)"
              strokeWidth="10"
            />
            <motion.circle
              cx="64"
              cy="64"
              r={RADIUS}
              fill="none"
              stroke={b.color}
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={CIRC}
              initial={{ strokeDashoffset: reduce ? targetOffset : CIRC }}
              animate={{ strokeDashoffset: targetOffset }}
              transition={{ duration: 1.4, ease: [0.16, 1, 0.3, 1] }}
              style={{ filter: `drop-shadow(0 0 8px color-mix(in srgb, ${b.color} 55%, transparent))` }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div
              className="font-mono text-4xl font-semibold tabular-nums text-glow"
              style={
                {
                  "--glow": `color-mix(in srgb, ${b.color} 45%, transparent)`,
                } as React.CSSProperties
              }
            >
              <AnimatedNumber value={value} />
              <span className="ml-0.5 text-xl text-muted-foreground">%</span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
