"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import type { ReactNode } from "react";

export const sectionContainer: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1, delayChildren: 0.05 } },
};

export const sectionItem: Variants = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] } },
};

type Props = {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
};

// Section shell with a staggered entrance. Animates on MOUNT (not whileInView): a section
// living inside an initially-hidden tab panel and below the fold would never satisfy the
// IntersectionObserver, leaving it stuck at opacity:0 — this is what made the SEO/GEO
// Recommendations blocks render blank. Mount animation always settles at opacity:1, so the
// section is visible whenever it has content (mirrors the RecCard fix in this codebase).
export function Section({ title, subtitle, action, children }: Props) {
  const reduce = useReducedMotion();
  return (
    <motion.section
      initial={reduce ? "show" : "hidden"}
      animate="show"
      variants={sectionContainer}
      className="mt-12 sm:mt-16"
    >
      <motion.div
        variants={sectionItem}
        className="mb-5 flex items-end justify-between gap-4"
      >
        <div>
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h2>
          {subtitle && (
            <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
          )}
        </div>
        {action}
      </motion.div>
      {children}
    </motion.section>
  );
}
