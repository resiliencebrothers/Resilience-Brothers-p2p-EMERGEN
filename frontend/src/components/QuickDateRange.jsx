/**
 * QuickDateRange — reusable quick-pick range buttons.
 *
 * Renders a compact row of chips that pre-fill a since/until date range
 * for common accounting windows: last 7 days, this month, this year.
 *
 * Callers control the range via `since`/`until` props (ISO date strings,
 * "YYYY-MM-DD") and receive updates via a single `onRangeChange` callback
 * `({ since, until }) => void`. The clear chip resets both bounds to "".
 *
 * The active preset is auto-detected from the current `since`/`until` so
 * the chip stays highlighted after a refresh or a route change.
 */
import { useTranslation } from "react-i18next";

/**
 * Format a Date as "YYYY-MM-DD" using the LOCAL timezone (browser wall-clock).
 *
 * The <input type="date"> value is a naive local-day string with no tz,
 * so if we used `.toISOString().slice(0,10)` a user in UTC-6 opening the
 * dialog at 22:00 local time on Jan 1st would get "2026-01-02" (the UTC
 * day), which off-by-one's the range. Formatting via the local getters
 * matches what a bare date picker would emit for the same day.
 */
function fmtLocalDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function computeQuickRange(preset, now = new Date()) {
  if (preset === "7d") {
    const from = new Date(now);
    from.setDate(from.getDate() - 6); // inclusive of today = 7 days
    return { since: fmtLocalDate(from), until: fmtLocalDate(now) };
  }
  if (preset === "month") {
    const from = new Date(now.getFullYear(), now.getMonth(), 1);
    return { since: fmtLocalDate(from), until: fmtLocalDate(now) };
  }
  if (preset === "year") {
    const from = new Date(now.getFullYear(), 0, 1);
    return { since: fmtLocalDate(from), until: fmtLocalDate(now) };
  }
  return { since: "", until: "" };
}

/**
 * Detect which preset (if any) the current `since`/`until` values match,
 * comparing against the same date arithmetic used to fill them.
 */
export function detectActivePreset(since, until, now = new Date()) {
  if (!since || !until) return null;
  for (const p of ["7d", "month", "year"]) {
    const r = computeQuickRange(p, now);
    if (r.since === since && r.until === until) return p;
  }
  return null;
}

export default function QuickDateRange({
  since,
  until,
  onRangeChange,
  testIdPrefix = "quick-range",
  className = "",
}) {
  const { t } = useTranslation();
  const active = detectActivePreset(since, until);
  const isEmpty = !since && !until;

  const apply = (preset) => () => onRangeChange(computeQuickRange(preset));
  const clear = () => onRangeChange({ since: "", until: "" });

  const buttons = [
    { key: "7d", label: t("quickRange.last7Days"), testId: `${testIdPrefix}-7d` },
    { key: "month", label: t("quickRange.thisMonth"), testId: `${testIdPrefix}-month` },
    { key: "year", label: t("quickRange.thisYear"), testId: `${testIdPrefix}-year` },
  ];

  const base =
    "h-8 px-3 text-[0.65rem] font-mono uppercase tracking-wider rounded-none border transition-colors";
  const inactive = "border-white/10 text-neutral-400 hover:border-[#8B5CF6]/60 hover:text-white";
  const activeCls = "border-[#8B5CF6] text-white bg-[#8B5CF6]/15";

  return (
    <div
      data-testid={`${testIdPrefix}-row`}
      className={`flex flex-wrap items-center gap-2 ${className}`}
    >
      {buttons.map((b) => (
        <button
          key={b.key}
          type="button"
          data-testid={b.testId}
          onClick={apply(b.key)}
          className={`${base} ${active === b.key ? activeCls : inactive}`}
        >
          {b.label}
        </button>
      ))}
      {!isEmpty && (
        <button
          type="button"
          data-testid={`${testIdPrefix}-clear`}
          onClick={clear}
          className="h-8 px-2 text-[0.65rem] font-mono uppercase tracking-wider rounded-none text-neutral-500 hover:text-[#8B5CF6] underline underline-offset-4"
        >
          {t("quickRange.clear")}
        </button>
      )}
    </div>
  );
}
