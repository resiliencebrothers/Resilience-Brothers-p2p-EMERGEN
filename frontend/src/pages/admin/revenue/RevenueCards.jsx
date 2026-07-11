function Row({ label, value, accent }) {
  return (
    <div className="flex justify-between border-b border-white/5 py-2 last:border-0">
      <span className="text-neutral-500">{label}</span>
      <span className={accent ? "text-[#22C55E] font-semibold" : "text-white"}>{value}</span>
    </div>
  );
}

export function BigStat({ icon: Icon, label, value, unit, highlight, hint, testid }) {
  return (
    <div
      className={
        "relative overflow-hidden bg-[#141322] border border-white/5 rounded-xl p-5 " +
        "transition-all duration-300 ease-out " +
        "hover:-translate-y-0.5 hover:border-violet-500/30 " +
        "hover:shadow-[0_8px_24px_-12px_rgba(139,92,246,0.2)] " +
        (highlight
          ? "shadow-[0_0_20px_rgba(139,92,246,0.15)] border-violet-500/40 "
          : "")
      }
      data-testid={testid}
    >
      <Icon
        className={
          "absolute top-5 right-5 w-5 h-5 " +
          (highlight ? "text-[#22C55E]" : "text-violet-400/60")
        }
      />
      <div className="text-[11px] font-semibold tracking-[0.2em] text-white/50 uppercase mb-2">
        {label}
      </div>
      <div className="font-mono tabular-nums tracking-tight text-3xl font-medium text-white">
        {value} <span className="text-sm text-neutral-400 font-sans">{unit}</span>
      </div>
      {hint ? (
        <div className="text-xs text-neutral-500 mt-2 font-mono tabular-nums">
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export function RoleCard({ title, subtitle, data, accent }) {
  return (
    <div className={`tactile-card p-6 border ${accent}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-display text-lg">{title}</h3>
          <p className="text-xs text-neutral-500">{subtitle}</p>
        </div>
      </div>
      <div className="space-y-2 font-mono text-sm">
        <Row label="Órdenes" value={data.orders} />
        <Row
          label="Volumen"
          value={`${(data.volume_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT`}
        />
        <Row
          label="Ganancia generada"
          value={`${(data.profit_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT`}
          accent
        />
      </div>
    </div>
  );
}
