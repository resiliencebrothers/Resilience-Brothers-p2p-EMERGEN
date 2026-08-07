/**
 * iter142 — ProfitDetailDialog
 *
 * Drill-down for the "Rentabilidad total" chip in a FundCard. Fetches the
 * exact P2P orders (matching to_code) and VIP batch items (matching
 * from_code) that add up to that card's profit_total, with a per-row
 * profit column expressed in the currency being audited.
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { ArrowRightLeft, Layers, TrendingUp } from "lucide-react";

const fmt = (n) =>
  Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });

const fmtRate = (n) => {
  const v = Number(n || 0);
  if (!v) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 4,
  });
};

export default function ProfitDetailDialog({ currency, onClose }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!currency) { setData(null); return undefined; }
    let ignore = false;
    setLoading(true);
    axios.get(`${API}/admin/company-funds/profit-detail/${encodeURIComponent(currency)}`, {
      withCredentials: true,
    })
      .then((r) => { if (!ignore) setData(r.data); })
      .catch(() => {
        if (!ignore) toast.error(t("admin.companyFunds.profitDetailLoadError"));
      })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [currency, t]);

  const empty = data && !data.orders?.length && !data.batches?.length;

  return (
    <Dialog open={!!currency} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="profit-detail-dialog"
        className="bg-[#0c0c0c] border border-[#22C55E]/30 text-white rounded-none max-w-3xl max-h-[85vh] overflow-y-auto tx-body-scroll"
      >
        <DialogHeader>
          <DialogTitle className="font-mono flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-[#22C55E]" />
            {t("admin.companyFunds.profitDetailTitle", { currency })}
          </DialogTitle>
          <DialogDescription className="text-xs text-neutral-500">
            {t("admin.companyFunds.profitDetailSub", { currency })}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="text-sm text-neutral-500 py-8 text-center" data-testid="profit-detail-loading">
            {t("admin.common.loadingEllipsis")}
          </div>
        )}

        {!loading && data && (
          <div className="space-y-5">
            <div className="flex items-center justify-between border border-[#22C55E]/25 bg-[#22C55E]/5 px-4 py-3">
              <span className="micro-label text-neutral-400">
                {t("admin.companyFunds.profitDetailTotal")}
              </span>
              <span
                className="font-mono text-lg text-[#22C55E] font-bold"
                data-testid="profit-detail-total"
              >
                {fmt(data.profit_total)} {currency}
              </span>
            </div>

            {empty && (
              <div
                className="text-sm text-neutral-500 py-8 text-center border border-white/5 bg-black/20"
                data-testid="profit-detail-empty"
              >
                {t("admin.companyFunds.profitDetailEmpty")}
              </div>
            )}

            {data.orders?.length > 0 && (
              <Section
                icon={ArrowRightLeft}
                title={t("admin.companyFunds.profitOrdersSection", { currency })}
                count={data.orders.length}
                subtotalLabel={t("admin.companyFunds.profitOrdersSubtotal")}
                subtotalValue={`${fmt(data.orders_profit_total)} ${currency}`}
                testid="profit-orders-section"
              >
                <table className="w-full text-sm">
                  <thead className="bg-[#0a0a0a] sticky top-0">
                    <tr className="text-left">
                      <Th>{t("admin.companyFunds.profitColDate")}</Th>
                      <Th>{t("admin.companyFunds.profitColClient")}</Th>
                      <Th>{t("admin.companyFunds.profitColPair")}</Th>
                      <Th right>{t("admin.companyFunds.profitColSends")}</Th>
                      <Th right>{t("admin.companyFunds.profitColReceives")}</Th>
                      <Th right>{t("admin.companyFunds.profitColProfit")}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.orders.map((o) => (
                      <tr key={o.id} className="border-b border-white/5" data-testid={`profit-order-row-${o.id}`}>
                        <Td>{o.reviewed_at ? new Date(o.reviewed_at).toLocaleDateString() : "—"}</Td>
                        <Td>{o.user_name}</Td>
                        <Td><span className="text-[#A78BFA]">{o.pair}</span></Td>
                        <Td right>{fmt(o.amount_from)} <span className="text-neutral-500">{o.from_code}</span></Td>
                        <Td right>{fmt(o.amount_to)} <span className="text-neutral-500">{o.to_code}</span></Td>
                        <Td right><Profit v={o.profit} currency={currency} /></Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}

            {data.batches?.length > 0 && (
              <Section
                icon={Layers}
                title={t("admin.companyFunds.profitBatchesSection", { currency })}
                count={data.batches.length}
                subtotalLabel={t("admin.companyFunds.profitBatchesSubtotal")}
                subtotalValue={`${fmt(data.batches_profit_total)} ${currency}`}
                testid="profit-batches-section"
              >
                <table className="w-full text-sm">
                  <thead className="bg-[#0a0a0a] sticky top-0">
                    <tr className="text-left">
                      <Th>{t("admin.companyFunds.profitColDate")}</Th>
                      <Th>{t("admin.companyFunds.profitColClient")}</Th>
                      <Th>{t("admin.companyFunds.profitColHolder")}</Th>
                      <Th>{t("admin.companyFunds.profitColPair")}</Th>
                      <Th right>{t("admin.companyFunds.profitColSends")}</Th>
                      <Th right>{t("admin.companyFunds.profitColRates")}</Th>
                      <Th right>{t("admin.companyFunds.profitColProfit")}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.batches.map((b) => (
                      <tr key={b.id} className="border-b border-white/5" data-testid={`profit-batch-row-${b.id}`}>
                        <Td>{b.reviewed_at ? new Date(b.reviewed_at).toLocaleDateString() : "—"}</Td>
                        <Td>{b.vip_name}</Td>
                        <Td className="font-mono">{b.holder}</Td>
                        <Td><span className="text-[#A78BFA]">{b.pair}</span></Td>
                        <Td right>{fmt(b.amount)} <span className="text-neutral-500">{b.from_code}</span></Td>
                        <Td right>
                          <span className="text-neutral-300">{fmtRate(b.rate_applied)}</span>
                          <span className="text-neutral-600"> / </span>
                          <span className="text-[#22C55E]">{fmtRate(b.real_rate)}</span>
                        </Td>
                        <Td right><Profit v={b.profit} currency={currency} /></Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({ icon: Icon, title, count, subtotalLabel, subtotalValue, testid, children }) {
  return (
    <div className="border border-white/5 bg-black/20" data-testid={testid}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5 gap-2 flex-wrap">
        <span className="micro-label text-neutral-400 flex items-center gap-2">
          <Icon className="w-4 h-4 text-[#8B5CF6]" />
          {title}
          <span className="text-neutral-600 font-mono">({count})</span>
        </span>
        <span className="flex items-center gap-1.5 text-xs">
          <span className="text-neutral-500">{subtotalLabel}:</span>
          <span className="font-mono text-[#22C55E]">{subtotalValue}</span>
        </span>
      </div>
      <div className="overflow-x-auto max-h-[300px] tx-body-scroll">
        {children}
      </div>
    </div>
  );
}

function Th({ children, right }) {
  return (
    <th className={`px-3 py-2 micro-label text-neutral-500 whitespace-nowrap ${right ? "text-right" : ""}`}>
      {children}
    </th>
  );
}

function Td({ children, right, className = "" }) {
  return (
    <td className={`px-3 py-2 font-mono text-xs text-neutral-300 whitespace-nowrap ${right ? "text-right" : ""} ${className}`}>
      {children}
    </td>
  );
}

function Profit({ v, currency }) {
  const n = Number(v) || 0;
  return (
    <span className={`font-semibold ${n >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
      {fmt(n)} <span className="text-neutral-500">{currency}</span>
    </span>
  );
}
