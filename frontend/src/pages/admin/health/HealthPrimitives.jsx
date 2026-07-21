/**
 * Shared primitives for the AdminHealth dashboard: StatCard and Section
 * shells. Both are pure presentational components.
 */
export function StatCard({ icon: Icon, label, value, sub, tone = "default", testid, action }) {
  const toneClass = {
    default: "border-white/10",
    danger: "border-red-500/40 bg-red-500/5",
    warn: "border-amber-500/40 bg-amber-500/5",
    ok: "border-emerald-500/30 bg-emerald-500/5",
  }[tone];
  return (
    <div data-testid={testid} className={`p-5 border ${toneClass} space-y-1`}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-neutral-400">
        <Icon className="w-4 h-4" />
        {label}
      </div>
      <div className="font-display text-3xl text-white">{value}</div>
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
      {action && <div className="pt-2">{action}</div>}
    </div>
  );
}

export function Section({ title, children, action }) {
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between">
        <h2 className="font-display text-lg text-[#8B5CF6]">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
