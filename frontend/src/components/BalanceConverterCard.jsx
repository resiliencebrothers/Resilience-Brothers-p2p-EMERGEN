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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { ArrowRightLeft, Wallet, ChevronDown } from "lucide-react";

export default function BalanceConverterCard({ onConverted }) {
  const { user } = useAuth();
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
    setToCode(currencyCode === "USDT"
      ? (currencies.find((c) => c.code !== "USDT")?.code || "USD")
      : "USDT");
    setAmount("");
    setOpen(true);
  };

  const previewRate = computeRate(fromCode, toCode);
  const previewAmount = previewRate && amount
    ? Number(parseFloat(amount) * previewRate)
    : null;

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
    setBusy(true);
    try {
      const r = await axios.post(
        `${API}/vip/convert`,
        { from_code: fromCode, to_code: toCode, amount_from: amt },
        { withCredentials: true },
      );
      toast.success(
        `Convertiste ${amt} ${fromCode} en ${r.data.amount_to} ${toCode}.`,
      );
      setOpen(false);
      await loadBalances();
      if (onConverted) await onConverted();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error en la conversión");
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
          <ArrowRightLeft className="w-5 h-5 text-[#EAB308]" />
          Convertir Saldos
        </h2>
        <div
          className="text-xs text-neutral-500"
          data-testid="balance-converter-total"
        >
          Total ≈ <span className="text-[#EAB308] font-mono">
            {(balances.total_usdt || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
          </span>
        </div>
      </div>
      <div className="space-y-2">
        {visible.map((b) => (
          <div
            key={b.currency}
            className="flex items-center justify-between border border-white/5 hover:border-[#EAB308]/30 transition-colors p-3"
            data-testid={`converter-row-${b.currency}`}
          >
            <div>
              <div className="font-mono text-sm text-neutral-200">
                {Number(b.amount).toLocaleString(undefined, { maximumFractionDigits: 4 })}
                <span className="text-neutral-500 ml-1">{b.currency}</span>
              </div>
              {b.usdt_equivalent != null && b.currency !== "USDT" && (
                <div className="text-[0.65rem] text-neutral-600 font-mono mt-0.5">
                  ≈ {b.usdt_equivalent.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT
                </div>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => openDialog(b.currency)}
              className="text-[#EAB308] hover:bg-[#EAB308]/10 rounded-none gap-1"
              data-testid={`converter-trigger-${b.currency}`}
            >
              <ArrowRightLeft className="w-3.5 h-3.5" />
              Convertir
            </Button>
          </div>
        ))}
      </div>
      {positive.length > 3 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-xs text-neutral-400 hover:text-[#EAB308] mt-3 flex items-center gap-1 transition-colors mx-auto"
          data-testid="balance-converter-show-all"
        >
          {showAll ? "Mostrar menos" : `Ver todas (${positive.length})`}
          <ChevronDown
            className={`w-3 h-3 transition-transform ${showAll ? "rotate-180" : ""}`}
          />
        </button>
      )}

      {/* Conversion dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#111] border-white/10 text-white rounded-none">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2" data-testid="converter-dialog-title">
              Convertir {fromCode}
              <ArrowRightLeft className="w-4 h-4 text-[#EAB308]" />
              {toCode}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-4">
            <div className="text-xs text-neutral-400">
              Mueve fondos entre tus propias monedas al tipo de cambio {isVip ? "VIP" : "estándar"}.
              No requiere aprobación del staff.
            </div>
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
                    .filter((c) => c.code !== fromCode)
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
                  className="text-xs text-[#EAB308] h-12 rounded-none px-3 hover:bg-[#EAB308]/10"
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
            <div
              className="border border-white/10 p-3 bg-[#0a0a0a]"
              data-testid="converter-preview"
            >
              {previewRate === null && toCode && fromCode && toCode !== fromCode && (
                <div className="text-xs text-red-400" data-testid="converter-preview-no-rate">
                  No hay tasa cotizada para {fromCode} → {toCode}.
                </div>
              )}
              {previewRate !== null && (
                <>
                  <div className="flex justify-between items-baseline">
                    <span className="text-xs text-neutral-500">Recibirás:</span>
                    <span
                      className="font-mono text-lg text-[#EAB308]"
                      data-testid="converter-preview-amount"
                    >
                      {previewAmount === null
                        ? `~ ${toCode}`
                        : `${Number(previewAmount.toFixed(4)).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${toCode}`}
                    </span>
                  </div>
                  <div className="text-[0.65rem] text-neutral-600 font-mono mt-1">
                    Tasa: 1 {fromCode} = {previewRate.toFixed(6)} {toCode}
                  </div>
                </>
              )}
            </div>
            <Button
              data-testid="confirm-converter"
              onClick={submit}
              disabled={busy || !amount || previewRate === null}
              className="w-full bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none h-12 flex items-center justify-center gap-2"
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
