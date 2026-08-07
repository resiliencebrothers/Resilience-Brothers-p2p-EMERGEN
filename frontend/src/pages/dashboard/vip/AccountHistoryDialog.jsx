import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { PiggyBank, ArrowUpFromLine, ArrowRightLeft } from "lucide-react";
import { DepositHistory } from "./DepositForm";
import { VipWithdrawalHistory } from "./VipWithdrawalHistory";

/**
 * iter115 — Account history dialog for "Depósitos y Retiros": separate tabs
 * for deposits, withdrawals and self-conversions (owner request, exchange
 * style). Conversions come from /me/transactions?direction=conversion.
 */
export function AccountHistoryDialog({ open, onOpenChange, withdrawals, onChanged }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState("deposits");

  useEffect(() => { if (open) setTab("deposits"); }, [open]);

  const TABS = [
    { key: "deposits",    icon: PiggyBank,       label: t("vipView.historyDialog.tabs.deposits") },
    { key: "withdrawals", icon: ArrowUpFromLine, label: t("vipView.historyDialog.tabs.withdrawals") },
    { key: "conversions", icon: ArrowRightLeft,  label: t("vipView.historyDialog.tabs.conversions") },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="account-history-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-2xl max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("vipView.historyDialog.title")}</DialogTitle>
          <DialogDescription className="text-xs text-neutral-400">
            {t("vipView.historyDialog.subtitle")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-2 flex-wrap" role="tablist">
          {TABS.map(({ key, icon: Icon, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              data-testid={`history-tab-${key}`}
              className={`flex items-center gap-2 text-xs uppercase tracking-widest px-3 py-2 border font-mono transition-colors ${
                tab === key
                  ? "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#A78BFA]"
                  : "border-white/10 text-neutral-400 hover:border-white/30"
              }`}
            >
              <Icon className="w-3.5 h-3.5" /> {label}
            </button>
          ))}
        </div>

        <div className="mt-2">
          {tab === "deposits" && <DepositHistory alwaysShow />}
          {tab === "withdrawals" && (
            <VipWithdrawalHistory withdrawals={withdrawals} onChanged={onChanged} />
          )}
          {tab === "conversions" && <ConversionsHistory active={open} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}


function ConversionsHistory({ active }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!active) return;
    setLoading(true);
    axios.get(`${API}/me/transactions`, {
      params: { direction: "conversion", limit: 100 },
      withCredentials: true,
    })
      .then((r) => setItems(r.data?.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [active]);

  if (loading) {
    return <div className="text-sm text-neutral-500 py-6 text-center">{t("admin.common.loadingEllipsis")}</div>;
  }
  if (items.length === 0) {
    return (
      <div className="text-sm text-neutral-500 py-8 text-center border border-white/5 bg-black/20" data-testid="conversions-empty">
        {t("vipView.historyDialog.conversionsEmpty")}
      </div>
    );
  }
  return (
    <div className="space-y-2 max-h-[50vh] overflow-y-auto" data-testid="conversions-history">
      {items.map((c) => (
        <div
          key={c.ref_id}
          className="flex items-center justify-between text-xs border border-white/5 bg-black/20 px-3 py-2.5"
          data-testid={`conversion-row-${c.ref_id}`}
        >
          <div className="flex items-center gap-2 min-w-0">
            <ArrowRightLeft className="w-3.5 h-3.5 text-sky-400 shrink-0" />
            <span className="font-mono text-white whitespace-nowrap">
              {Number(c.amount).toLocaleString(undefined, { maximumFractionDigits: 4 })} {c.from_code || c.currency}
            </span>
            <span className="text-neutral-500">→</span>
            <span className="font-mono text-emerald-400 whitespace-nowrap">
              {Number(c.amount_to || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })} {c.to_code}
            </span>
          </div>
          <span className="text-[0.6rem] text-neutral-500 shrink-0 ml-3">
            {c.created_at ? new Date(c.created_at).toLocaleDateString() : ""}
          </span>
        </div>
      ))}
    </div>
  );
}
