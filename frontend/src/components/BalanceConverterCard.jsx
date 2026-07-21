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
import { useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { extractDetailMessage } from "@/utils/apiErrors";
import { toast } from "sonner";
import { ArrowRightLeft, Wallet, ChevronDown, Sparkles } from "lucide-react";
import { BalanceRow } from "@/components/converter/BalanceRow";
import ConvertDialog from "@/components/converter/ConvertDialog";
import DustSweepDialog from "@/components/converter/DustSweepDialog";
import { useConverterData } from "@/components/converter/useConverterData";

// iter55.36i — universal 0.01 USDT fee on EVERY allowed conversion, and
// the source amount must be worth ≥ 1.00 USDT equivalent. Mirrors the
// backend rules in `routes/orders.py::vip_convert`.
const CONVERT_FEE_USDT = 0.01;
const CONVERT_MIN_SOURCE_USDT = 1.0;
// iter79 — matches SMALL_BALANCE_THRESHOLD_USDT in services/transactions.py.
const DUST_THRESHOLD_USDT = 5.0;

export default function BalanceConverterCard({ onConverted }) {
  const { user } = useAuth();
  const { t } = useTranslation();
  const isVip = user?.role === "vip" || user?.role === "admin";
  const isEmployee = user?.role === "employee";

  const { balances, currencies, positive, computeRate, toUsdt, refresh } =
    useConverterData({ isVip, enabled: !isEmployee });

  const [open, setOpen] = useState(false);
  const [fromCode, setFromCode] = useState("");
  const [toCode, setToCode] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  // iter79 — Dust sweep button visible only when the user actually has
  // something to sweep (any positive non-USDT balance whose USDT eq < 5).
  const [dustOpen, setDustOpen] = useState(false);
  const dustBalances = useMemo(
    () => positive.filter(
      (b) => b.currency !== "USDT"
        && Number(b.usdt_equivalent || 0) > 0
        && Number(b.usdt_equivalent || 0) < DUST_THRESHOLD_USDT,
    ),
    [positive],
  );

  const visible = useMemo(
    () => (showAll ? positive : positive.slice(0, 3)),
    [positive, showAll],
  );

  // Employees don't see this widget. Hooks must run before any early return.
  if (isEmployee) return null;

  const openDialog = (currencyCode) => {
    setFromCode(currencyCode);
    // iter77 — Pick the FIRST convertible destination that ALSO has a rate
    // configured FROM the source currency. Avoids showing "No configured
    // rate" on dialog open just because the alphabetical first destination
    // happens to lack a rate.
    const hasRate = (dst) => computeRate(currencyCode, dst) !== null;
    const convertibleTargets = currencies.filter(
      (c) => c.code !== currencyCode && c.is_convertible_to !== false,
    );
    const withRate = convertibleTargets.filter((c) => hasRate(c.code));
    const preferred = currencyCode === "USDT"
      ? withRate.find((c) => c.code !== "USDT")
      : withRate.find((c) => c.code === "USDT") || withRate[0];
    const defaultTarget = preferred?.code
      || convertibleTargets[0]?.code
      || (currencyCode === "USDT" ? "USD" : "USDT");
    setToCode(defaultTarget);
    setAmount("");
    setOpen(true);
  };

  const previewRate = computeRate(fromCode, toCode);
  // iter77 — Fee model:
  //   • Destination receives the FULL equivalent (`amount × rate`).
  //   • 0.01 USDT is charged SEPARATELY from the client's USDT balance.
  //   • If source is USDT, total USDT needed = amount + 0.01.
  //   • If source is NOT USDT, USDT balance must have ≥ 0.01 available.
  //   Preview matches backend exactly (`routes/orders.py::vip_convert`).
  const previewSourceUsdt = amount ? toUsdt(parseFloat(amount), fromCode) : null;
  const belowMinSource = previewSourceUsdt !== null && previewSourceUsdt < CONVERT_MIN_SOURCE_USDT;
  const previewNet = previewRate && amount ? parseFloat(amount) * previewRate : null;
  // Check the USDT balance can cover the fee (and the source amount when
  // source itself is USDT). Used to preemptively disable the confirm button.
  const usdtBalance = Number(positive.find((b) => b.currency === "USDT")?.amount || 0);
  const requiredUsdt = CONVERT_FEE_USDT + (fromCode === "USDT" ? (parseFloat(amount) || 0) : 0);
  const insufficientUsdtForFee = amount && usdtBalance < requiredUsdt;

  const onMax = () => {
    const b = positive.find((x) => x.currency === fromCode);
    if (!b) return;
    // iter77 — When converting USDT→X, MAX must leave 0.01 USDT for the fee
    // so the confirmation doesn't bounce back with "insufficient USDT".
    if (fromCode === "USDT") {
      const maxAvailable = Math.max(0, Number(b.amount) - CONVERT_FEE_USDT);
      setAmount(String(maxAvailable));
    } else {
      setAmount(String(b.amount));
    }
  };

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
    if (belowMinSource) {
      return toast.error(
        `Mínimo por conversión: equivalente a ${CONVERT_MIN_SOURCE_USDT.toFixed(2)} USDT.` +
        (previewSourceUsdt !== null
          ? ` Tu monto equivale a ${previewSourceUsdt.toFixed(4)} USDT.`
          : ""),
      );
    }
    // iter77 — Guard: USDT balance must cover the fee.
    const totalUsdtNeeded = CONVERT_FEE_USDT + (fromCode === "USDT" ? amt : 0);
    if (usdtBalance < totalUsdtNeeded) {
      if (fromCode === "USDT") {
        return toast.error(
          `Saldo insuficiente en USDT: necesitas al menos ${totalUsdtNeeded.toFixed(2)} USDT ` +
          `(${amt.toFixed(2)} para convertir + ${CONVERT_FEE_USDT.toFixed(2)} de comisión). ` +
          `Tienes ${usdtBalance.toFixed(4)} USDT.`,
        );
      }
      return toast.error(
        `Necesitas al menos ${CONVERT_FEE_USDT.toFixed(2)} USDT en tu saldo para pagar la comisión. ` +
        `Tienes ${usdtBalance.toFixed(4)} USDT.`,
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
      // iter77 — Fee is now debited separately; the toast still reports it
      // to close the loop with the client.
      const feeSuffix = fee > 0 ? ` (comisión ${fee} USDT descontada aparte)` : "";
      toast.success(
        `Convertiste ${amt} ${fromCode} en ${r.data.amount_to} ${toCode}${feeSuffix}.`,
      );
      setOpen(false);
      await refresh();
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

      {/* iter79 — Dust sweep CTA. Only shown when there is dust to sweep. */}
      {dustBalances.length > 0 && (
        <button
          type="button"
          onClick={() => setDustOpen(true)}
          data-testid="dust-sweep-open"
          className="mt-4 w-full flex items-center justify-between gap-2 px-3 py-2 border border-[#8B5CF6]/25 bg-[#8B5CF6]/5 hover:bg-[#8B5CF6]/10 hover:border-[#8B5CF6]/50 transition-colors text-left group"
        >
          <span className="flex items-center gap-2 text-xs text-neutral-300 group-hover:text-white">
            <Sparkles className="w-3.5 h-3.5 text-[#8B5CF6]" />
            <span>
              {t("balanceConverter.dustCta", { count: dustBalances.length })}
            </span>
          </span>
          <span className="text-[0.6rem] font-mono text-[#8B5CF6] uppercase tracking-wider">
            &lt; {DUST_THRESHOLD_USDT} USDT
          </span>
        </button>
      )}

      <ConvertDialog
        open={open}
        onOpenChange={setOpen}
        isVip={isVip}
        fromCode={fromCode}
        toCode={toCode}
        amount={amount}
        onToCodeChange={setToCode}
        onAmountChange={setAmount}
        onMax={onMax}
        currencies={currencies}
        positive={positive}
        previewRate={previewRate}
        previewNet={previewNet}
        feeUsdt={CONVERT_FEE_USDT}
        minSourceUsdt={CONVERT_MIN_SOURCE_USDT}
        belowMinSource={belowMinSource}
        previewSourceUsdt={previewSourceUsdt}
        insufficientUsdtForFee={insufficientUsdtForFee}
        usdtBalance={usdtBalance}
        busy={busy}
        onSubmit={submit}
      />

      <DustSweepDialog
        open={dustOpen}
        onOpenChange={setDustOpen}
        onConverted={async () => {
          await refresh();
          if (onConverted) await onConverted();
        }}
      />
    </div>
  );
}
