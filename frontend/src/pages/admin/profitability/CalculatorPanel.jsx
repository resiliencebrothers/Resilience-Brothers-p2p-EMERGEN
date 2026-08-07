// iter115 — dual-mode calculator (mirrors Excel "Calculadora Unificada Dos Modos").
// Modo 1 (direct): buy in cash → sell in transfer. Modo 2 (combined): FX + transfer diff.
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TrendingUp, TrendingDown, Target } from "lucide-react";
import { computeUnit, computeDirect, fmt, fmtPct } from "./calc";

const COMBINED_FIELDS = [
  { key: "sell", labelKey: "profitability.calc.sellPrice", hintKey: "profitability.calc.sellHint", testid: "profit-calc-sell-input" },
  { key: "buy", labelKey: "profitability.calc.buyPrice", hintKey: "profitability.calc.buyHint", testid: "profit-calc-buy-input" },
  { key: "buyPct", labelKey: "profitability.calc.buyPct", testid: "profit-calc-buypct-input" },
  { key: "sellPct", labelKey: "profitability.calc.sellPct", testid: "profit-calc-sellpct-input" },
  { key: "qty", labelKey: "profitability.calc.quantity", testid: "profit-calc-qty-input" },
];

const DIRECT_FIELDS = [
  { key: "buy", labelKey: "profitability.calc.m1BuyPrice", hintKey: "profitability.calc.m1BuyHint", testid: "profit-calc-buy-input" },
  { key: "sell", labelKey: "profitability.calc.m1SellPrice", hintKey: "profitability.calc.m1SellHint", testid: "profit-calc-sell-input" },
  { key: "buyPct", labelKey: "profitability.calc.m1CostPct", testid: "profit-calc-buypct-input" },
  { key: "qty", labelKey: "profitability.calc.quantity", testid: "profit-calc-qty-input" },
];

export default function CalculatorPanel({ rates = [], calc, setCalc, pctFor = () => ({ buy_pct: 0, sell_pct: 0 }) }) {
  const { t } = useTranslation();
  const isDirect = calc.mode === "direct";
  const u = isDirect ? computeDirect(calc) : computeUnit(calc);
  const unit = calc.toCode || "";
  const set = (key) => (e) => setCalc((p) => ({ ...p, [key]: e.target.value }));
  const fields = isDirect ? DIRECT_FIELDS : COMBINED_FIELDS;

  const applyPair = (rateId) => {
    const r = rates.find((x) => x.id === rateId);
    if (!r) return;
    const pct = pctFor(r.to_code);
    setCalc((p) => ({
      ...p,
      pairId: r.id, fromCode: r.from_code, toCode: r.to_code,
      // real_rate = price the operator SELLS at; rate_normal = price paid to
      // the client, i.e. the operator's BUY cost (user-reported semantics).
      sell: r.real_rate === null || r.real_rate === undefined ? "" : String(r.real_rate),
      buy: r.rate_normal === null || r.rate_normal === undefined ? "" : String(r.rate_normal),
      buyPct: String(pct.buy_pct ?? 0),
      sellPct: String(pct.sell_pct ?? 0),
    }));
  };

  return (
    <div className="tactile-card p-5 space-y-5" data-testid="profit-calc-panel">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-display text-lg">{t("profitability.calc.title")}</h3>
        {rates.length > 0 && (
          <div className="w-56">
            <Select value={calc.pairId} onValueChange={applyPair}>
              <SelectTrigger data-testid="profit-calc-pair-select">
                <SelectValue placeholder={t("profitability.calc.pairPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {rates.map((r) => (
                  <SelectItem key={r.id} value={r.id}>{r.from_code} → {r.to_code}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <ModeButton
          active={isDirect}
          label={t("profitability.calc.mode1")}
          onClick={() => setCalc((p) => ({ ...p, mode: "direct" }))}
          testid="profit-mode-direct"
        />
        <ModeButton
          active={!isDirect}
          label={t("profitability.calc.mode2")}
          onClick={() => setCalc((p) => ({ ...p, mode: "combined" }))}
          testid="profit-mode-combined"
        />
      </div>

      <div className={`grid grid-cols-2 ${isDirect ? "md:grid-cols-4" : "md:grid-cols-5"} gap-3`}>
        {fields.map((f) => (
          <div key={f.key} className="space-y-1">
            <Label className="text-xs text-neutral-400">{t(f.labelKey)}</Label>
            <Input type="number" step="any" min="0" value={calc[f.key]} onChange={set(f.key)} data-testid={f.testid} />
            {f.hintKey && <p className="text-[0.6rem] text-neutral-500">{t(f.hintKey)}</p>}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <HeroCard
          icon={u.netGain >= 0 ? TrendingUp : TrendingDown}
          label={t("profitability.calc.netGain")}
          value={`${fmt(u.netGain)} ${unit}`}
          positive={u.netGain >= 0}
          testid="profit-net-gain"
        />
        <HeroCard
          icon={u.netGain >= 0 ? TrendingUp : TrendingDown}
          label={t(isDirect ? "profitability.calc.netMargin" : "profitability.calc.marginOnBuy")}
          value={fmtPct(isDirect ? u.marginOnSell : u.marginOnBuy)}
          positive={u.netGain >= 0}
          testid="profit-margin"
        />
        {isDirect ? (
          <HeroCard
            icon={Target}
            label={t("profitability.calc.m1MinSell")}
            value={`${fmt(u.minSellPrice)} ${unit}`}
            positive
            hint={t("profitability.calc.m1MinSellHint")}
            testid="profit-min-sell"
          />
        ) : (
          <HeroCard
            icon={Target}
            label={t("profitability.calc.maxBuy")}
            value={`${fmt(u.maxBuyPrice)} ${unit}`}
            positive
            hint={t("profitability.calc.maxBuyHint")}
            testid="profit-max-buy"
          />
        )}
      </div>

      {isDirect ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
          <DetailRow label={t("profitability.calc.m1RealCost")} value={`${fmt(u.realCost)} ${unit}`} />
          <DetailRow label={t("profitability.calc.m1MarginOnCost")} value={fmtPct(u.marginOnCost)} signed={u.netGain} />
          <DetailRow label={t("profitability.calc.cushion")} value={`${fmt(u.cushion)} ${unit}`} signed={u.cushion} />
          <DetailRow label={t("profitability.calc.m1TotalGain")} value={`${fmt(u.netGain * (Number(calc.qty) || 0))} ${unit}`} signed={u.netGain} />
        </div>
      ) : (
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1.5 text-sm">
          <DetailRow label={t("profitability.calc.resultFx")} value={`${fmt(u.resultFx)} ${unit}`} signed={u.resultFx} />
          <DetailRow label={t("profitability.calc.conversionGain")} value={`${fmt(u.conversionGain)} ${unit}`} signed={u.conversionGain} />
          <DetailRow label={t("profitability.calc.cushion")} value={`${fmt(u.cushion)} ${unit}`} signed={u.cushion} />
          <DetailRow label={t("profitability.calc.transferValue")} value={`${fmt(u.transferValue)} ${unit}`} />
          <DetailRow label={t("profitability.calc.recoveredCash")} value={`${fmt(u.recoveredCash)} ${unit}`} />
          <DetailRow label={t("profitability.calc.m1MinSell")} value={`${fmt(u.minSellPrice)} ${unit}`} />
          <DetailRow label={t("profitability.calc.marginOnSell")} value={fmtPct(u.marginOnSell)} signed={u.marginOnSell} />
        </div>
      )}
    </div>
  );
}

function ModeButton({ active, label, onClick, testid }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      className={`px-3.5 py-1.5 rounded-full text-xs border transition-colors ${active
        ? "border-[#8B5CF6]/60 text-[#A78BFA] bg-[#8B5CF6]/10 font-semibold"
        : "border-white/10 text-neutral-500 hover:text-neutral-300"}`}
    >
      {label}
    </button>
  );
}

function HeroCard({ icon: Icon, label, value, positive, hint, testid }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4" data-testid={testid}>
      <Icon className={`w-4 h-4 mb-1 ${positive ? "text-[#22C55E]" : "text-[#EF4444]"}`} />
      <div className="micro-label text-neutral-500">{label}</div>
      <div className={`font-display text-xl mt-0.5 ${positive ? "text-[#22C55E]" : "text-[#EF4444]"}`}>{value}</div>
      {hint && <p className="text-[0.6rem] text-neutral-500 mt-1">{hint}</p>}
    </div>
  );
}

function DetailRow({ label, value, signed }) {
  const color = signed === undefined ? "text-neutral-200" : signed >= 0 ? "text-[#22C55E]" : "text-[#EF4444]";
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/5 py-1 min-w-0">
      <span className="text-neutral-500 text-xs min-w-0">{label}</span>
      <span className={`font-mono text-xs whitespace-nowrap shrink-0 text-right ${color}`}>{value}</span>
    </div>
  );
}
