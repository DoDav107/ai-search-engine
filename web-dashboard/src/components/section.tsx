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

// Section shell with a staggered scroll-in entrance (matches the 2A hero animations).
export function Section({ title, subtitle, action, children }: Props) {
  const reduce = useReducedMotion();
  return (
    <motion.section
      initial={reduce ? "show" : "hidden"}
      whileInView="show"
      viewport={{ once: true, amount: 0.15 }}
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
