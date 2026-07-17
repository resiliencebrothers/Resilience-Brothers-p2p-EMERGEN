/**
 * Shared header block for admin pages. Standardises the eyebrow +
 * title + subtitle pattern used across every /admin/* view and lets
 * pages plug their own action bar (e.g. "Seed data", filters, refresh).
 *
 * Props are already-translated strings so the component stays purely
 * presentational (no i18n coupling). Callers pass `t("...")` in.
 */
export default function AdminPageHeader({
  eyebrow,
  title,
  subtitle,
  icon: Icon,
  actions,
  testid = "admin-page-header",
}) {
  return (
    <div
      className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-6 flex-wrap"
      data-testid={testid}
    >
      <div className="min-w-0">
        {eyebrow && (
          <div className="micro-label text-[#8B5CF6] mb-2">{eyebrow}</div>
        )}
        <h1 className="font-display text-3xl flex items-center gap-3">
          {Icon && <Icon className="w-7 h-7 text-[#8B5CF6]" />}
          {title}
        </h1>
        {subtitle && (
          <p className="text-neutral-400 mt-2 text-sm max-w-2xl">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2 flex-wrap">{actions}</div>
      )}
    </div>
  );
}
