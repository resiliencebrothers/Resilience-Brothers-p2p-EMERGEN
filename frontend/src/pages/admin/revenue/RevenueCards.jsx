import { useTranslation } from "react-i18next";

function Row({ label, value, accent }) {
  return (
    <div className="flex justify-between border-b border-white/5 py-2 last:border-0">
      <span className="text-neutral-500">{label}</span>
      <span className={accent ? "text-[#22C55E] font-semibold" : "text-white"}>{value}</span>
    </div>
  );
}

export function BigStat({ icon: Icon, label, value, unit, highlight, hint, testid }) {
  // iter157 — auto-scale the font so long amounts are never clipped by the
  // card (production bug: "58.511,72" rendered as "58.511,").
  const str = String(value ?? "");
  const sizeCls =
    str.length > 13 ? "text-lg" :
      str.length > 10 ? "text-xl" :
        str.length > 8 ? "text-2xl" : "text-3xl";
  return (
    <div
      className={
        "relative overflow-hidden bg-[#1A1730] border border-white/5 rounded-xl p-5 " +
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
      <div className="text-[11px] font-semibold tracking-[0.2em] text-white/50 uppercase mb-2 pr-8">
        {label}
      </div>
      <div className={`font-mono tabular-nums tracking-tight ${sizeCls} font-medium text-white break-words leading-tight`}>
        {value} <span className="text-sm text-neutral-400 font-sans whitespace-nowrap">{unit}</span>
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
  const { t } = useTranslation();
  const b = data.batches;
  const hasBatches = b && (b.orders > 0 || b.profit_usdt > 0);
  const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return (
    <div className={`tactile-card p-6 border ${accent}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-display text-lg">{title}</h3>
          <p className="text-xs text-neutral-500">{subtitle}</p>
        </div>
      </div>
      <div className="space-y-2 font-mono text-sm">
        <Row label={t("admin.revenue.roleOrders")} value={data.orders} />
        <Row
          label={t("admin.revenue.roleVolume")}
          value={`${fmt(data.volume_usdt)} USDT`}
        />
        <Row
          label={t("admin.revenue.roleProfitGenerated")}
          value={`${fmt(data.profit_usdt)} USDT`}
          accent
        />
      </div>
      {hasBatches && (
        <div
          className="mt-3 pt-3 border-t border-white/5 text-[0.65rem] font-mono text-neutral-500 space-y-0.5"
          data-testid="role-card-batches"
        >
          <div className="flex justify-between">
            <span className="uppercase tracking-widest text-[0.6rem] text-[#A78BFA]">
              {t("admin.revenue.vipBatchesBreakdown")}
            </span>
            <span className="text-neutral-400">{b.orders} · {fmt(b.volume_usdt)} · {fmt(b.profit_usdt)} USDT</span>
          </div>
        </div>
      )}
    </div>
  );
}
