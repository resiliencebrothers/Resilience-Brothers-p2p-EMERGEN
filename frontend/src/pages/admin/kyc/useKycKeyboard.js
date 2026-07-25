/**
 * iter100 — Extracted from AdminKYC.jsx.
 *
 * Keyboard-shortcut handler for the KYC review console:
 *   j/↓  → focus next   ·  k/↑ → focus previous
 *   a    → approve       ·  Shift+A → bulk approve batch
 *   r    → reject        ·  i → request more info
 *   x    → toggle batch  ·  ? → open help    ·  Escape → close help
 *
 * Guards:
 * - Ignores keydown when the user is typing (input/textarea/select/
 *   contentEditable) or when the action dialog is open.
 * - When the help modal is up, only `?` and Escape close it.
 */
import { useEffect } from "react";

const PENDING = new Set(["pending", "needs_more_info"]);

function isTyping(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function useKycKeyboard({
  items, focusedIdx, setFocusedIdx,
  selected, showHelp, setShowHelp,
  openAction, toggleBatch, bulkApprove,
}) {
  useEffect(() => {
    const handler = (e) => {
      if (isTyping(document.activeElement)) return;
      if (selected) return;
      if (showHelp) {
        if (e.key === "Escape" || e.key === "?") setShowHelp(false);
        return;
      }

      const focused = items[focusedIdx];
      const key = e.key;

      if (key === "j" || key === "J" || key === "ArrowDown") {
        e.preventDefault();
        setFocusedIdx((i) => Math.min(items.length - 1, i + 1));
        return;
      }
      if (key === "k" || key === "K" || key === "ArrowUp") {
        e.preventDefault();
        setFocusedIdx((i) => Math.max(0, i - 1));
        return;
      }
      if (key === "?") {
        e.preventDefault();
        setShowHelp(true);
        return;
      }
      if (!focused) return;

      // Shift+A → bulk approve. Some keyboards deliver 'A' (upper) and
      // some 'a'+shiftKey — we accept both.
      if (e.shiftKey && (key === "A" || key === "a")) {
        e.preventDefault();
        bulkApprove();
        return;
      }
      if (key === "a" && PENDING.has(focused.status)) {
        e.preventDefault();
        openAction(focused, "approve");
        return;
      }
      if ((key === "r" || key === "R") && PENDING.has(focused.status)) {
        e.preventDefault();
        openAction(focused, "reject");
        return;
      }
      if ((key === "i" || key === "I") && PENDING.has(focused.status)) {
        e.preventDefault();
        openAction(focused, "more_info");
        return;
      }
      if ((key === "x" || key === "X") && PENDING.has(focused.status)) {
        e.preventDefault();
        toggleBatch(focused.id);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    items, focusedIdx, setFocusedIdx,
    selected, showHelp, setShowHelp,
    openAction, toggleBatch, bulkApprove,
  ]);
}
