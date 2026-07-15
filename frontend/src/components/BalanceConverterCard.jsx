/**
 * iter50 — Reusable balance-converter widget.
 *
 * Self-contained card that:
 *   1. Fetches the user's multi-currency VIP balances + active currencies + rates.
 *   2. Renders each positive balance with an inline "Convertir" button.
 *   3. Opens a modal with origin/destination/amount + LIVE PREVIEW computed
 *      against the same inverse-fallback rate logic used by the backend.
 *
 *   Used by `OverviewView` (main client dashboard) and `MarketplaceView`.
 *   Available to BOTH `normal` and `vip` clients — the backend
 *   `POST /api/vip/convert` accepts both roles (only `employee` is blocked).
 *
 *   Props:
 *     - onConverted: optional callback fired after a successful conversion
 *       (parent components can refresh their own state, e.g. order list).
 */
import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { extractDetailMessage } from "@/utils/apiErrors";
import { toast } from "sonner";
import { ArrowRightLeft, Wallet, ChevronDown } from "lucide-react";
import { BalanceRow } from "@/components/converter/BalanceRow";
import { ConvertPreview } from "@/components/converter/ConvertPreview";

export default function BalanceConverterCard({ onConverted }) {
  const { user } = useAuth();
  const { t } = useTranslation();
  const isVip = user?.role === "vip" || user?.role === "admin";
  const isStaff = user?.role === "admin" || user?.role === "employee";

  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  const [rates, setRates] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [open, setOpen] = useState(false);
  const [fromCode, setFromCode] = useState("");
  const [toCode, setToCode] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const loadBalances = () =>
    axios.get(`${API}/vip/balances`, { withCredentials: true })
      .then((r) => setBalances(r.data))
      .catch(() => {});

  useEffect(() => {
    // Employees never have VIP balances → render nothing
    if (isStaff && user?.role === "employee") return;
    loadBalances();
    axios.get(`${API}/rates`).then((r) => setRates(r.data)).catch(() => {});
    axios.get(`${API}/currencies`)
      .then((r) => setCurrencies(r.data.filter((c) => c.is_active)))
      .catch(() => {});
  }, [isStaff, user?.role]);

  // iter53 — memoize the positive-balance filter (was recomputed on every
  // render of every interactive state change incl. dialog open/close).
  const positive = useMemo(
    () => (balances.balances || []).filter((b) => Number(b.amount) > 0),
    [balances.balances],
  );
  const visible = useMemo(
    () => (showAll ? positive : positive.slice(0, 3)),
    [positive, showAll],
  );

  // Employees don't see this widget. (hooks above must run first per rules-of-hooks)
  if (user?.role === "employee") return null;

  // Mirrors `services/balances.py::_convert_direct` (inverse-first).
  const computeRate = (f, t) => {
    if (!f || !t || f === t) return null;
    const pick = (r) => Number(isVip ? (r.rate_vip || r.rate_normal) : r.rate_normal);
    const direct = rates.find((r) => r.from_code === f && r.to_code === t);
    if (direct) {
      const v = pick(direct);
      if (v > 0) return v;
    }
    const inverse = rates.find((r) => r.from_code === t && r.to_code === f);
    if (inverse) {
      const inv = pick(inverse);
      if (inv > 0) return 1 / inv;
    }
    return null;
  };

  const openDialog = (currencyCode) => {
    setFromCode(currencyCode);
    // iter55.29 — first convertible target that isn't the source. Falls back
    // to any active non-source currency if the catalog has no explicit
    // convertible currencies (defensive).
    const convertibleTargets = currencies.filter(
      (c) => c.code !== currencyCode && c.is_convertible_to !== false,
    );
    const defaultTarget = currencyCode === "USDT"
      ? (convertibleTargets.find((c) => c.code !== "USDT")?.code
         || currencies.find((c) => c.code !== "USDT")?.code
         || "USD")
      : (convertibleTargets.find((c) => c.code === "USDT") ? "USDT"
         : (convertibleTargets[0]?.code || "USDT"));
    setToCode(defaultTarget);
    setAmount("");
    setOpen(true);
  };

  const previewRate = computeRate(fromCode, toCode);
  // iter55.36i — universal 0.01 USDT fee on EVERY allowed conversion, and
  // the source amount must be worth ≥ 1.00 USDT equivalent. Mirrors the
  // backend rules in `routes/orders.py::vip_convert`.
  const CONVERT_FEE_USDT = 0.01;
  const CONVERT_MIN_SOURCE_USDT = 1.0;

  // Helper: convert an amount in `code` to its USDT equivalent using the
  // same rate table the backend uses. Prefers the operator's inverse
  // valuation quote (USDT→code) then falls back to code→USDT direct.
  const toUsdt = (amt, code) => {
    if (amt == null || !code) return null;
    if (code === "USDT") return amt;
    const inverse = rates.find(r => r.from_code === "USDT" && r.to_code === code);
    if (inverse && inverse.rate_normal > 0) return amt / inverse.rate_normal;
    const direct = rates.find(r => r.from_code === code && r.to_code === "USDT");
    if (direct && direct.rate_normal > 0) return amt * direct.rate_normal;
    return null;
  };
  // Fee expressed in the destination currency (for preview UI only — backend
  // is the source of truth in the response).
  const feeInToCode = (() => {
    if (!toCode) return null;
    if (toCode === "USDT") return CONVERT_FEE_USDT;
    const direct = rates.find(r => r.from_code === "USDT" && r.to_code === toCode);
    if (direct && direct.rate_normal > 0) return CONVERT_FEE_USDT * direct.rate_normal;
    const inverse = rates.find(r => r.from_code === toCode && r.to_code === "USDT");
    if (inverse && inverse.rate_normal > 0) return CONVERT_FEE_USDT / inverse.rate_normal;
    return null;
  })();
  const previewGross = previewRate && amount
    ? Number(parseFloat(amount) * previewRate)
    : null;
  const previewNet = (previewGross == null || feeInToCode == null)
    ? previewGross
    : Math.max(0, previewGross - feeInToCode);
  const previewSourceUsdt = amount ? toUsdt(parseFloat(amount), fromCode) : null;
  const belowMinSource = previewSourceUsdt !== null && previewSourceUsdt < CONVERT_MIN_SOURCE_USDT;

  const submit = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) return toast.error("Cantidad inválida");
    if (!toCode || toCode === fromCode) {
      return toast.error("Selecciona una moneda destino diferente");
    }
    const have = positive.find((b) => b.currency === fromCode);
    if (!have || Number(have.amount) < amt) {
      return toast.error(`No tienes ${amt} ${fromCode} disponible.`);
    }
    // iter55.36i — client-side minimum-source guard mirroring backend
    if (belowMinSource) {
      return toast.error(
        `Mínimo por conversión: equivalente a ${CONVERT_MIN_SOURCE_USDT.toFixed(2)} USDT.` +
        (previewSourceUsdt !== null
          ? ` Tu monto equivale a ${previewSourceUsdt.toFixed(4)} USDT.`
          : "")
      );
    }
    setBusy(true);
    try {
      const r = await axios.post(
        `${API}/vip/convert`,
        { from_code: fromCode, to_code: toCode, amount_from: amt },
        { withCredentials: true },
      );
      const fee = r.data.usdt_fee;
      const feeInDest = r.data.fee_in_to_code;
      const feeSuffix = fee > 0
        ? ` (comisión ${fee} USDT${feeInDest && toCode !== "USDT" ? ` ≈ ${feeInDest} ${toCode}` : ""})`
        : "";
      toast.success(
        `Convertiste ${amt} ${fromCode} en ${r.data.amount_to} ${toCode}${feeSuffix}.`,
      );
      setOpen(false);
      await loadBalances();
      if (onConverted) await onConverted();
    } catch (e) {
      toast.error(extractDetailMessage(e, "Error en la conversión"));
    } finally { setBusy(false); }
  };

  if (positive.length === 0) {
    return (
      <div
        className="tactile-card p-6 text-center"
        data-testid="balance-converter-empty"
      >
        <Wallet className="w-8 h-8 text-neutral-600 mx-auto mb-3" />
        <div className="text-sm text-neutral-400">
          Aún no tienes saldo acumulado.
        </div>
        <div className="text-xs text-neutral-600 mt-1">
          Recibe pagos en transferencia/efectivo para activar tu billetera.
        </div>
      </div>
    );
  }

  return (
    <div className="tactile-card p-6" data-testid="balance-converter-card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display text-xl flex items-center gap-2">
          <ArrowRightLeft className="w-5 h-5 text-[#8B5CF6]" />
          {t("balanceConverter.title")}
        </h2>
        <div
          className="text-xs text-neutral-500"
          data-testid="balance-converter-total"
        >
          {t("balanceConverter.totalPrefix")} <span className="text-[#8B5CF6] font-mono">
            {(balances.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
          </span>
        </div>
      </div>
      <div className="space-y-2">
        {visible.map((b) => (
          <BalanceRow key={b.currency} balance={b} onConvert={openDialog} />
        ))}
      </div>
      {positive.length > 3 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-xs text-neutral-400 hover:text-[#8B5CF6] mt-3 flex items-center gap-1 transition-colors mx-auto"
          data-testid="balance-converter-show-all"
        >
          {showAll ? t("balanceConverter.showLess") : t("balanceConverter.showAll", { count: positive.length })}
          <ChevronDown
            className={`w-3 h-3 transition-transform ${showAll ? "rotate-180" : ""}`}
          />
        </button>
      )}

      {/* Conversion dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#111] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2" data-testid="converter-dialog-title">
              {t("balanceConverter.dialogTitle")} {fromCode}
              <ArrowRightLeft className="w-4 h-4 text-[#8B5CF6]" />
              {toCode}
            </DialogTitle>
            <DialogDescription className="text-neutral-400 text-xs">
              Mueve fondos entre tus propias monedas al tipo de cambio {isVip ? "VIP" : "estándar"}.
              {" "}Cada conversión permitida tiene una comisión fija de {CONVERT_FEE_USDT.toFixed(2)} USDT y un mínimo por operación equivalente a {CONVERT_MIN_SOURCE_USDT.toFixed(2)} USDT.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 pt-4">
            <div>
              <Label className="micro-label text-neutral-500">Moneda destino</Label>
              <Select value={toCode} onValueChange={setToCode}>
                <SelectTrigger
                  data-testid="converter-to-code"
                  className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
                >
                  <SelectValue placeholder="Selecciona destino" />
                </SelectTrigger>
                <SelectContent className="bg-[#111] border-white/10 text-white">
                  {currencies
                    .filter((c) => c.code !== fromCode && c.is_convertible_to !== false)
                    .map((c) => (
                      <SelectItem
                        key={c.code}
                        value={c.code}
                        data-testid={`converter-to-option-${c.code}`}
                      >
                        {c.code} · {c.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">
                Cantidad de {fromCode}
              </Label>
              <div className="flex items-center gap-2 mt-2">
                <Input
                  data-testid="converter-amount"
                  type="number"
                  min="0"
                  step="any"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono"
                />
                <Button
                  variant="ghost"
                  className="text-xs text-[#8B5CF6] h-12 rounded-none px-3 hover:bg-[#8B5CF6]/10"
                  onClick={() => {
                    const b = positive.find((x) => x.currency === fromCode);
                    if (b) setAmount(String(b.amount));
                  }}
                  data-testid="converter-max"
                >MÁX</Button>
              </div>
              {fromCode && (
                <div className="text-[0.65rem] text-neutral-500 mt-1 font-mono">
                  Saldo: {(positive.find((x) => x.currency === fromCode)?.amount || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })} {fromCode}
                </div>
              )}
            </div>
            <ConvertPreview
              fromCode={fromCode}
              toCode={toCode}
              previewRate={previewRate}
              previewGross={previewGross}
              previewNet={previewNet}
              feeInToCode={feeInToCode}
              feeUsdt={CONVERT_FEE_USDT}
              belowMinSource={belowMinSource}
              minSourceUsdt={CONVERT_MIN_SOURCE_USDT}
              previewSourceUsdt={previewSourceUsdt}
            />
            <Button
              data-testid="confirm-converter"
              onClick={submit}
              disabled={busy || !amount || previewRate === null || belowMinSource}
              className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-12 flex items-center justify-center gap-2"
            >
              <ArrowRightLeft className="w-4 h-4" />
              {busy ? "Convirtiendo..." : "Confirmar conversión"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
