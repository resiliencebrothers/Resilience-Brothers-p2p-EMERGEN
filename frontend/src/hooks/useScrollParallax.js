import { useEffect, useState } from "react";

/**
 * iter55.30g — Subtle scroll-parallax hook for the Landing hero constellations.
 * Returns the current `window.scrollY` throttled via `requestAnimationFrame`
 * (called at most once per frame — no re-renders per pixel).
 *
 * Respects `prefers-reduced-motion`: users who opted out of motion effects
 * get a stable value of 0 (no transform will be applied).
 *
 * Usage:
 *   const scrollY = useScrollParallax();
 *   <div style={{ transform: `translateY(${scrollY * 0.3}px)` }} />
 */
export function useScrollParallax() {
  const [scrollY, setScrollY] = useState(0);

  useEffect(() => {
    const reduceMotion = typeof window !== "undefined"
      && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return undefined;

    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        setScrollY(window.scrollY || 0);
        raf = 0;
      });
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, []);

  return scrollY;
}
