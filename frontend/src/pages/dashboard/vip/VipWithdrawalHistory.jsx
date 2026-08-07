import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import { WithdrawalDetailDialog } from "./WithdrawalDetailDialog";

const WITHDRAWAL_STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  cancelled: "bg-neutral-700/20 text-neutral-400 border-neutral-700/40",
  pending: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
};

// iter55.36s — status labels resolved via i18n key at render time.
// key format: `withdraw.historyLabel.{method}.{status}`
function getWithdrawalKey(method, status) {
  const knownMethods = new Set(["cash", "transfer", "crypto"]);
  const m = knownMethods.has(method) ? method : "transfer";
  return `withdraw.historyLabel.${m}.${status}`;
}

/**
 * iter153 — Withdrawal history rows are now clickable: each opens the
 * exchange-style WithdrawalDetailDialog with the progress timeline, payout
 * evidence and (while pending) the self-service cancel button.
 */
export function VipWithdrawalHistory({ withdrawals, onChanged }) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState(null);
  return (
    <div className="tactile-card p-6">
      <h2 className="font-display text-xl mb-4">{t("withdraw.historyTitleFull")}</h2>
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {withdrawals.length === 0 && (
          <p className="text-neutral-500 text-sm">{t("withdraw.historyEmpty")}</p>
        )}
        {withdrawals.map((w) => (
          <WithdrawalRow key={w.id} w={w} onOpen={() => setSelected(w)} />
        ))}
      </div>
      <WithdrawalDetailDialog
        w={selected}
        onClose={() => setSelected(null)}
        onChanged={onChanged}
      />
    </div>
  );
}


function WithdrawalRow({ w, onOpen }) {
  const { t } = useTranslation();
  const label = t(getWithdrawalKey(w.method, w.status), { defaultValue: w.status });
  const statusStyle = WITHDRAWAL_STATUS_STYLES[w.status] || WITHDRAWAL_STATUS_STYLES.pending;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full text-left border border-white/10 hover:border-[#8B5CF6]/40 transition-colors p-3 text-sm"
      data-testid={`withdrawal-row-${w.id}`}
    >
      <div className="flex justify-between items-start gap-2">
        <div className="min-w-0">
          <div className="font-mono">
            {w.amount_usd} {w.currency || "USD"} · {w.method}
            {w.crypto_network ? ` · ${w.crypto_network}` : ""}
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            {new Date(w.created_at).toLocaleString()}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${statusStyle}`}>
            {label}
          </span>
          <ChevronRight className="w-4 h-4 text-neutral-600" />
        </div>
      </div>
      <div className="text-[0.65rem] text-neutral-600 mt-2">
        {t("withdraw.rowDetailHint")}
      </div>
    </button>
  );
}
