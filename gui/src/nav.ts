// Route changes run inside a same-document view transition when the browser has
// them (Baseline 2025); elsewhere navigation is instant. flushSync makes React
// commit the new page inside the transition callback.
import { flushSync } from "react-dom";
import type { AroundNavHandler } from "wouter";

export const aroundNav: AroundNavHandler = (navigate, to, options) => {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!document.startViewTransition || reduced) {
    navigate(to, options);
    return;
  }
  document.startViewTransition(() => {
    flushSync(() => navigate(to, options));
  });
};
