import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Copy, AlertTriangle } from "lucide-react";

function CopyBtn({ text, testid }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={copy} data-testid={testid} className="text-[#8B5CF6] hover:text-[#A78BFA] shrink-0">
      {copied ? <CheckCircle2 className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
    </button>
  );
}

// iter143 — Tier-aware destination account. When the source currency has
// tiered accounts configured, the account matching the typed amount is
// shown (or a below-minimum warning). Legacy single-account currencies
// keep the old behaviour via `fromCurr.payment_account`.
export default function PaymentAccountBlock({ fromCurr, amount, paymentAccount }) {
  const { t } = useTranslation();
  const pa = paymentAccount || {};
  const amt = Number(amount) || 0;

  if (pa.hasTiers) {
    if (amt <= 0) {
      return (
        <div className="border border-white/10 p-4 text-xs text-neutral-500" data-testid="payment-account-enter-amount">
          {t("exchange.accountEnterAmount")}
        </div>
      );
    }
    if (pa.belowMin) {
      return (
        <div className="border border-amber-500/40 bg-amber-500/5 p-4 flex items-start gap-2" data-testid="payment-account-min-warning">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-400">
            {t("exchange.minAmountWarning", { code: fromCurr?.code || "", min: pa.minRequired })}
          </p>
        </div>
      );
    }
    if (!pa.account) {
      if (pa.loading) return null;
      return (
        <div className="border border-amber-500/40 bg-amber-500/5 p-4 text-xs text-amber-400" data-testid="payment-account-none">
          {t("exchange.noAccountForAmount")}
        </div>
      );
    }
    return (
      <div className="border border-emerald-500/25 bg-emerald-500/5 p-4" data-testid="payment-account-block">
        <div className="micro-label text-emerald-400 mb-2">{t("exchange.sendExactly")}</div>
        <div className="flex items-center justify-between gap-3 mb-1">
          <span className="text-sm text-white font-semibold" data-testid="payment-account-label">{pa.account.label}</span>
          <CopyBtn text={pa.account.account_details} testid="payment-account-copy" />
        </div>
        {pa.account.network ? (
          <div
            className="mt-2 mb-3 border border-amber-500/50 bg-amber-500/10 px-3 py-2 flex items-start gap-2"
            data-testid="payment-account-network-warning"
          >
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="text-xs text-amber-200 leading-relaxed">
              <span className="font-semibold uppercase tracking-widest">
                {t("exchange.networkWarningLine", {
                  code: fromCurr?.code || "",
                  network: pa.account.network,
                })}
              </span>
              <div className="text-amber-300/80 text-[0.65rem] font-normal mt-0.5">
                {t("exchange.networkWarningHint")}
              </div>
            </div>
          </div>
        ) : null}
        <pre className="text-xs text-neutral-200 whitespace-pre-wrap font-mono leading-relaxed" data-testid="payment-account-details">
          {pa.account.account_details}
        </pre>
        <div className="text-[0.65rem] text-neutral-500 mt-2 font-mono">
          {t("exchange.accountMinHint", { min: pa.account.min_amount })}
          {pa.account.max_amount ? ` ${t("exchange.accountMaxHint", { max: pa.account.max_amount })}` : ""}
        </div>
      </div>
    );
  }

  if (!fromCurr?.payment_account) return null;
  return (
    <div className="border border-white/10 p-4">
      <div className="micro-label text-neutral-500 mb-2">{t("exchange.destinationAccount")}</div>
      <div className="flex items-center justify-between gap-3">
        <code className="text-sm break-all">{fromCurr.payment_account}</code>
        <CopyBtn text={fromCurr.payment_account} testid="copy-account-btn" />
      </div>
    </div>
  );
}
