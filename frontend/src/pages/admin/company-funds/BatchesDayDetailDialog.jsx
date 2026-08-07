import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Layers, ListChecks } from "lucide-react";

const fmt = (n) =>
  Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function BatchesDayDetailDialog({ date, onClose }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!date) { setData(null); return undefined; }
    let ignore = false;
    axios.get(`${API}/admin/company-funds/batches-today/detail`, {
      params: { date }, withCredentials: true,
    })
      .then((r) => { if (!ignore) setData(r.data); })
      .catch(() => { if (!ignore) setData(null); });
    return () => { ignore = true; };
  }, [date]);

  const empty = data && !data.batches.length && !data.orders.length;

  return (
    <Dialog open={!!date} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="batches-day-detail-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-3xl max-h-[85vh] overflow-y-auto tx-body-scroll"
      >
        <DialogHeader>
          <DialogTitle className="font-mono">
            {t("admin.companyFunds.batchesToday.detailTitle", { date })}
          </DialogTitle>
          <DialogDescription className="text-xs text-neutral-500">
            {t("admin.companyFunds.batchesToday.detailSub")}
          </DialogDescription>
        </DialogHeader>
        {data && (
          <div className="space-y-5">
            {empty && (
              <div
                className="text-sm text-neutral-500 py-8 text-center border border-white/5 bg-black/20"
                data-testid="batches-day-empty"
              >
                {t("admin.companyFunds.batchesToday.emptyDay")}
              </div>
            )}

            {data.batches.length > 0 && (
              <DaySection
                icon={Layers}
                title={t("admin.companyFunds.batchesToday.batchesSection")}
                count={data.batches.length}
                testid="day-batches-section"
              >
                <table className="w-full text-sm">
                  <thead className="bg-[#0a0a0a] sticky top-0">
                    <tr className="text-left">
                      <Th>{t("admin.revenue.colPair")}</Th>
                      <Th>{t("admin.revenue.ddClient")}</Th>
                      <Th>{t("admin.companyFunds.batchesToday.colOrders")}</Th>
                      <Th right>{t("admin.companyFunds.batchesToday.colApproved")}</Th>
                      <Th right>{t("admin.companyFunds.batchesToday.colClose")}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.batches.map((b) => (
                      <tr key={b.id} className="border-b border-white/5">
                        <Td><span className="text-[#A78BFA]">{b.pair}</span></Td>
                        <Td>{b.vip_name}</Td>
                        <Td>{b.items_approved}✓ · {b.items_pending}⧗ · {b.items_rejected}✗</Td>
                        <Td right>
                          {fmt(b.amount_approved)} <span className="text-neutral-500">{b.from_code}</span>
                        </Td>
                        <Td right>
                          {b.closed_at ? new Date(b.closed_at).toLocaleTimeString() : "—"}
                          {b.auto_closed && (
                            <span className="text-[0.55rem] text-[#A78BFA] ml-1.5 border border-[#A78BFA]/40 px-1 py-0.5 uppercase tracking-widest">
                              auto
                            </span>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DaySection>
            )}

            {data.orders.length > 0 && (
              <DaySection
                icon={ListChecks}
                title={t("admin.companyFunds.batchesToday.ordersSection")}
                count={data.orders.length}
                subtotal={`${fmt(data.volume_usdt)} USDT`}
                testid="day-orders-section"
              >
                <table className="w-full text-sm">
                  <thead className="bg-[#0a0a0a] sticky top-0">
                    <tr className="text-left">
                      <Th>{t("admin.revenue.ddTime")}</Th>
                      <Th>{t("admin.revenue.ddClient")}</Th>
                      <Th>{t("admin.revenue.ddCardHolder")}</Th>
                      <Th>{t("admin.revenue.colPair")}</Th>
                      <Th right>{t("admin.revenue.ddSends")}</Th>
                      <Th right>{t("admin.revenue.ddReceives")}</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.orders.map((o) => (
                      <tr key={o.id} className="border-b border-white/5">
                        <Td>{o.reviewed_at ? new Date(o.reviewed_at).toLocaleTimeString() : "—"}</Td>
                        <Td>{o.vip_name}</Td>
                        <Td>{o.holder}</Td>
                        <Td><span className="text-[#A78BFA]">{o.pair}</span></Td>
                        <Td right>{fmt(o.amount)} <span className="text-neutral-500">{o.from_code}</span></Td>
                        <Td right>
                          {o.amount_to != null
                            ? <span className="text-[#22C55E]">{fmt(o.amount_to)} <span className="text-neutral-500">{o.to_code}</span></span>
                            : "—"}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DaySection>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DaySection({ icon: Icon, title, count, subtotal, testid, children }) {
  return (
    <div className="border border-white/5 bg-black/20" data-testid={testid}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5">
        <span className="micro-label text-neutral-400 flex items-center gap-2">
          <Icon className="w-4 h-4 text-[#8B5CF6]" />
          {title}
          <span className="text-neutral-600 font-mono">({count})</span>
        </span>
        {subtotal && <span className="font-mono text-sm text-[#22C55E]">{subtotal}</span>}
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

function Td({ children, right }) {
  return (
    <td className={`px-3 py-2 font-mono text-xs text-neutral-300 whitespace-nowrap ${right ? "text-right" : ""}`}>
      {children}
    </td>
  );
}
