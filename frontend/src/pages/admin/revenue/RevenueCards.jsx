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
      className={`tactile-card p-5 ${highlight ? "glow-yellow" : ""}`}
      data-testid={testid}
    >
      <Icon className={`w-5 h-5 mb-3 ${highlight ? "text-[#22C55E]" : "text-[#8B5CF6]"}`} />
      <div className="micro-label text-neutral-500">{label}</div>
      <div className="font-display text-2xl mt-1">
        {value} <span className="text-sm text-neutral-400">{unit}</span>
      </div>
      {hint ? (
        <div className="text-xs text-neutral-500 mt-2 font-mono">{hint}</div>
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
