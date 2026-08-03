import { useState, useRef, useEffect, useCallback } from "react";

/**
 * Ago 2026 — Reusable "top horizontal scrollbar" wrapper (pattern born in
 * TransactionTable.jsx, owner request). Renders a custom draggable purple
 * scrollbar ABOVE the scrollable body so users never have to scroll to the
 * bottom of a long table to pan horizontally. Body + thumb stay in sync.
 */
export function TopScrollTable({ children, deps = [], maxHeightClass = "max-h-[70vh]", testid = "top-scroll-table" }) {
  const bodyScrollRef = useRef(null);
  const trackRef = useRef(null);
  const [contentWidth, setContentWidth] = useState(0);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [thumbLeft, setThumbLeft] = useState(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const measure = () => {
      const body = bodyScrollRef.current;
      if (body) {
        setContentWidth(body.scrollWidth);
        setViewportWidth(body.clientWidth);
      }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const overflow = Math.max(0, contentWidth - viewportWidth);
  const hasOverflow = overflow > 4;
  const trackW = viewportWidth || 0;
  const thumbW = hasOverflow ? Math.max(40, (trackW * trackW) / (contentWidth || 1)) : 0;
  const maxThumbLeft = Math.max(0, trackW - thumbW);

  const onBodyScroll = useCallback(() => {
    const body = bodyScrollRef.current;
    if (!body) return;
    const ratio = overflow > 0 ? body.scrollLeft / overflow : 0;
    setThumbLeft(ratio * maxThumbLeft);
  }, [overflow, maxThumbLeft]);

  const scrollToThumb = useCallback((nextLeft) => {
    const clamped = Math.max(0, Math.min(maxThumbLeft, nextLeft));
    setThumbLeft(clamped);
    const body = bodyScrollRef.current;
    if (body && maxThumbLeft > 0) {
      body.scrollLeft = (clamped / maxThumbLeft) * overflow;
    }
  }, [maxThumbLeft, overflow]);

  useEffect(() => {
    if (!dragging) return;
    const state = { startX: dragging.startX, startLeft: dragging.startLeft };
    const onMove = (e) => {
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      scrollToThumb(state.startLeft + (clientX - state.startX));
    };
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    };
  }, [dragging, scrollToThumb]);

  const onThumbDown = (e) => {
    e.preventDefault();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    setDragging({ startX: clientX, startLeft: thumbLeft });
  };

  const onTrackClick = (e) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    scrollToThumb(e.clientX - rect.left - thumbW / 2);
  };

  return (
    <>
      {hasOverflow && (
        <div
          ref={trackRef}
          onClick={onTrackClick}
          className="relative h-3 bg-[#0a0a0a] border-b border-[#8B5CF6]/20 cursor-pointer select-none"
          data-testid={`${testid}-top-scrollbar`}
          aria-hidden="true"
        >
          <div
            onMouseDown={onThumbDown}
            onTouchStart={onThumbDown}
            onClick={(e) => e.stopPropagation()}
            className="absolute top-0.5 bottom-0.5 rounded-full bg-[#8B5CF6] hover:bg-[#A78BFA] transition-colors cursor-grab active:cursor-grabbing shadow-[0_0_8px_rgba(139,92,246,0.5)]"
            style={{ left: `${thumbLeft}px`, width: `${thumbW}px` }}
            data-testid={`${testid}-top-scrollbar-thumb`}
          />
        </div>
      )}
      <div
        ref={bodyScrollRef}
        onScroll={onBodyScroll}
        className={`tx-body-scroll overflow-x-auto overflow-y-auto ${maxHeightClass}`}
        data-testid={`${testid}-body-scroll`}
      >
        {children}
      </div>
    </>
  );
}
