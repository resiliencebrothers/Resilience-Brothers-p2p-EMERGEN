import { useEffect, useRef, useState } from "react";

/**
 * iter160 — TradingView-style balance flash. Wrap a rendered amount and pass
 * the RAW numeric `value`; when it increases the text flashes green, when it
 * decreases it flashes red, then fades back to the inherited color.
 *
 * Changes within the first 1.5s after mount are treated as the initial data
 * load (state goes 0 → fetched value) and do NOT flash.
 */
export function FlashNumber({ value, children, className = "", testid }) {
  const prevRef = useRef(value);
  const mountedAtRef = useRef(Date.now());
  const [flash, setFlash] = useState(null); // null | "up" | "down"
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const a = Number(prevRef.current);
    const b = Number(value);
    if (Number.isFinite(a) && Number.isFinite(b) && a !== b) {
      if (Date.now() - mountedAtRef.current > 1500) {
        setFlash(b > a ? "up" : "down");
        setTick((n) => n + 1); // remount span → restarts the CSS animation
      }
    }
    prevRef.current = value;
  }, [value]);

  useEffect(() => {
    if (!flash) return undefined;
    const id = setTimeout(() => setFlash(null), 1600);
    return () => clearTimeout(id);
  }, [flash, tick]);

  const flashCls =
    flash === "up" ? "balance-flash-up" : flash === "down" ? "balance-flash-down" : "";

  return (
    <span
      key={tick}
      data-testid={testid}
      data-flash={flash || undefined}
      className={`${className} ${flashCls}`.trim()}
    >
      {children}
    </span>
  );
}
