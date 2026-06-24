"use client";

import { useEffect, useState } from "react";
import { animate, useReducedMotion } from "framer-motion";

type Props = {
  value: number;
  decimals?: number;
  duration?: number;
};

// Count-up animation that respects prefers-reduced-motion (jumps straight to the value).
export function AnimatedNumber({ value, decimals = 1, duration = 1.4 }: Props) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (reduce) {
      return;
    }
    const controls = animate(0, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [value, reduce, duration]);

  return <>{(reduce ? value : display).toFixed(decimals)}</>;
}
