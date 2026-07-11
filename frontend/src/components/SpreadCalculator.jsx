import { useState, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ArrowRight, Calculator, TrendingUp } from "lucide-react";

const fmt = (n, decimals = 4) => {
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: decimals });
};

export default function SpreadCalculator({ rates }) {
  const [pairId, setPairId] = useState("");
  const [amountStr, setAmountStr] = useState("100");

  const pair = useMemo(() => rates.find((r) => r.id === pairId) || null, [pairId, rates]);
  const amount = parseFloat(amountStr) || 0;

  const calc = useMemo(() => {
    if (!pair || amount <= 0) return null;
    const normalOut = amount * pair.rate_normal;
    const vipOut = amount * pair.rate_vip;
    const spread = vipOut - normalOut; // extra que el VIP recibe vs el normal (= margen del negocio al servir normal vs vip)
    const spreadPct = ((pair.rate_vip - pair.rate_normal) / pair.rate_normal) * 100;
    const real = pair.real_rate != null ? Number(pair.real_rate) : null;
    const marginNormal = real != null ? (real - pair.rate_normal) * amount : null;
    const marginVip = real != null ? (real - pair.rate_vip) * amount : null;
    return { normalOut, vipOut, spread, spreadPct, real, marginNormal, marginVip };
  }, [pair, amount]);

  return (
    <div className="tactile-card p-5 lg:p-6 mb-6" data-testid="spread-calculator">
      <div className="flex items-center gap-2 mb-4">
        <Calculator className="w-4 h-4 text-[#8B5CF6]" />
        <h2 className="font-display text-lg">Calculadora de Spread</h2>
        <span className="micro-label text-neutral-500 ml-2">/ comparativo por orden</span>
      </div>

      <div className="grid md:grid-cols-[1fr_1fr_auto] gap-3 mb-5">
        <div>
          <Label className="micro-label text-neutral-500">Par</Label>
          <Select value={pairId} onValueChange={setPairId}>
            <SelectTrigger data-testid="spread-pair-select" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10">
              <SelectValue placeholder="Selecciona un par" />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              {rates.map((r) => (
                <SelectItem key={r.id} value={r.id} className="rounded-none">
                  {r.from_code} → {r.to_code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="micro-label text-neutral-500">Monto enviado ({pair?.from_code || "—"})</Label>
          <Input
            data-testid="spread-amount-input"
            type="number"
            step="any"
            min="0"
            value={amountStr}
            onChange={(e) => setAmountStr(e.target.value)}
            placeholder="100"
            className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono"
          />
        </div>
      </div>

      {!calc && (
        <p className="text-neutral-500 text-sm font-mono">
          {rates.length === 0 ? "Crea al menos una tasa para usar la calculadora." : "Selecciona un par y un monto para ver el comparativo."}
        </p>
      )}

      {calc && pair && (
        <div className="space-y-4" data-testid="spread-result">
          {/* CLIENT VIEW — what each role receives */}
          <div className="grid md:grid-cols-2 gap-3">
            <div className="border border-white/10 bg-[#0a0a0a] p-4">
              <div className="micro-label text-neutral-500 mb-1">/ Cliente Normal</div>
              <div className="text-[0.65rem] text-neutral-600 font-mono mb-2">tasa {fmt(pair.rate_normal, 6)}</div>
              <div className="font-mono text-2xl text-white" data-testid="spread-normal-out">
                {fmt(calc.normalOut)} <span className="text-sm text-neutral-500">{pair.to_code}</span>
              </div>
            </div>
            <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-4">
              <div className="micro-label text-[#8B5CF6] mb-1">/ Cliente VIP</div>
              <div className="text-[0.65rem] text-neutral-600 font-mono mb-2">tasa {fmt(pair.rate_vip, 6)}</div>
              <div className="font-mono text-2xl text-white" data-testid="spread-vip-out">
                {fmt(calc.vipOut)} <span className="text-sm text-neutral-500">{pair.to_code}</span>
              </div>
            </div>
          </div>

          {/* SPREAD — your margin over VIPs when serving a normal client */}
          <div className="border-l-2 border-[#22C55E] bg-[#22C55E]/5 px-4 py-3 flex items-center gap-3" data-testid="spread-margin-block">
            <TrendingUp className="w-5 h-5 text-[#22C55E] shrink-0" />
            <div className="flex-1">
              <div className="micro-label text-[#22C55E] mb-0.5">Tu margen sobre VIPs por orden</div>
              <p className="text-xs text-neutral-400">
                El VIP recibe <span className="text-white font-mono">{fmt(calc.spread)}</span> {pair.to_code} más que el normal. Eso es lo que te queda extra cuando le sirves a un cliente normal en lugar de VIP.
              </p>
            </div>
            <div className="font-mono text-right">
              <div className="text-xl text-[#22C55E]" data-testid="spread-amount-out">+{fmt(calc.spread)}</div>
              <div className="text-[0.65rem] text-neutral-500 uppercase tracking-widest">{pair.to_code} · {fmt(calc.spreadPct, 2)}%</div>
            </div>
          </div>

          {/* MARKET MARGIN — only if real_rate is configured */}
          {calc.real != null && (
            <div className="border border-white/10 bg-[#0a0a0a] p-4" data-testid="spread-market-block">
              <div className="flex items-center justify-between mb-3">
                <div className="micro-label text-neutral-500">Margen vs. mercado <span className="text-[#22C55E]">(real {fmt(calc.real, 4)})</span></div>
                <span className="text-[0.65rem] text-neutral-600 font-mono">si compras al mercado y vendes al cliente</span>
              </div>
              <div className="grid grid-cols-2 gap-3 font-mono text-sm">
                <div className="flex items-center justify-between border-r border-white/5 pr-3">
                  <span className="text-neutral-400 text-xs">Por orden Normal</span>
                  <span className={calc.marginNormal >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"} data-testid="margin-normal-out">
                    {calc.marginNormal >= 0 ? "+" : ""}{fmt(calc.marginNormal)} {pair.to_code}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-neutral-400 text-xs">Por orden VIP</span>
                  <span className={calc.marginVip >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"} data-testid="margin-vip-out">
                    {calc.marginVip >= 0 ? "+" : ""}{fmt(calc.marginVip)} {pair.to_code}
                  </span>
                </div>
              </div>
              {calc.marginVip != null && calc.marginVip < 0 && (
                <p className="text-[0.7rem] text-[#EF4444] mt-3 leading-relaxed">
                  ⚠ Estás vendiendo al VIP a una tasa peor que el mercado. Revisa rate_vip antes de continuar.
                </p>
              )}
            </div>
          )}

          {/* QUICK FORMULA STRIP */}
          <div className="border-t border-white/5 pt-3 text-[0.65rem] text-neutral-600 font-mono flex flex-wrap items-center gap-2">
            <span>{fmt(amount, 2)} {pair.from_code}</span>
            <ArrowRight className="w-3 h-3" />
            <span>normal × {fmt(pair.rate_normal, 6)} = {fmt(calc.normalOut)} {pair.to_code}</span>
            <span className="text-neutral-700">·</span>
            <span>VIP × {fmt(pair.rate_vip, 6)} = {fmt(calc.vipOut)} {pair.to_code}</span>
          </div>
        </div>
      )}
    </div>
  );
}
