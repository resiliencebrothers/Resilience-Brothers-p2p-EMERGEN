/**
 * iter84 — SecurityUiPrimitives
 *
 * Small reusable UI atoms shared across the AdminSecurity page:
 *   • SummaryCard  — the 4 top-of-page metric tiles.
 *   • Panel        — the collapsible-looking section wrapper with icon.
 *   • Empty        — italicised placeholder when a table has no rows.
 *   • TableSimple  — the tabular data view used by audit lists.
 *
 * Previously inlined at the bottom of AdminSecurity.jsx — extracted so
 * the presentation modules can reuse them without circular imports.
 */

export function SummaryCard({ icon: Icon, label, value, hint, tone = "default", testId }) {
  const cls = {
    default: "border-white/5 bg-black/30 text-white",
    warn: "border-[#8B5CF6]/30 bg-[#8B5CF6]/5 text-[#FEF3C7]",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
  }[tone];
  return (
    <div data-testid={testId} className={`border ${cls} px-4 py-3`}>
      <div className="flex items-center gap-2 text-[0.65rem] uppercase tracking-wider text-neutral-500 mb-1">
        <Icon className="w-3.5 h-3.5" /> {label}
      </div>
      <div className="text-2xl font-bold">{value}</div>
      {hint && <div className="text-[0.65rem] text-neutral-500 mt-1">{hint}</div>}
    </div>
  );
}

export function Panel({ icon: Icon, title, subtitle, children }) {
  return (
    <div className="border border-white/5 bg-black/20 p-4">
      <div className="flex items-start gap-2 mb-3">
        <Icon className="w-4 h-4 text-[#8B5CF6] mt-0.5" />
        <div>
          <div className="text-sm font-semibold text-white">{title}</div>
          <div className="text-[0.7rem] text-neutral-500 leading-relaxed">{subtitle}</div>
        </div>
      </div>
      {children}
    </div>
  );
}

export function Empty({ text }) {
  return (
    <div className="text-xs text-neutral-500 italic border border-white/5 bg-black/30 px-3 py-3 text-center">
      {text}
    </div>
  );
}

export function TableSimple({ headers, rows }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[0.6rem] uppercase tracking-wider text-neutral-500 border-b border-white/5">
            {headers.map((h) => (
              <th key={h} className="text-left py-2 pr-3 font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row[0]}-${i}`} className="border-b border-white/5">
              {row.map((cell, j) => (
                <td key={`${row[0]}-${j}`} className="py-1.5 pr-3 text-neutral-300 font-mono text-[0.7rem]">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
