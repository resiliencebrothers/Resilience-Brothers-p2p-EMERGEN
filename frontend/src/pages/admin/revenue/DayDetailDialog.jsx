import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { ArrowRightLeft, ShoppingBag, Layers, Percent } from "lucide-react";

export function DayDetailDialog({ date, onClose, fmt }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!date) { setData(null); return undefined; }
    let ignore = false;
    setLoading(true);
    axios.get(`${API}/admin/revenue/day-detail`, { params: { date }, withCredentials: true })
      .then((r) => { if (!ignore) setData(r.data); })
      .catch(() => { if (!ignore) toast.error(t("admin.revenue.ddLoadError")); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [date, t]);

  const empty = data && !data.orders?.length && !data.marketplace?.length
    && !data.vip_batch_items?.length && !data.conversions?.length;

  return (
    <Dialog open={!!date} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="day-detail-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-3xl max-h-[85vh] overflow-y-auto tx-body-scroll"
      >
        <DialogHeader>
          <DialogTitle className="font-mono">{t("admin.revenue.ddTitle", { date })}</DialogTitle>
          <DialogDescription className="text-xs text-neutral-500">
            {t("admin.revenue.dailySubtitle")}
          </DialogDescription>
        </DialogHeader>
        {loading && (
          <div className="text-sm text-neutral-500 py-8 text-center">
            {t("admin.common.loadingEllipsis")}
          </div>
        )}
        {!loading && data && (
          <div className="space-y-5">
            <div className="flex items-center justify-between border border-[#22C55E]/25 bg-[#22C55E]/5 px-4 py-3">
              <span className="micro-label text-neutral-400">{t("admin.revenue.ddTotal")}</span>
              <span className="font-mono text-lg text-[#22C55E] font-bold" data-testid="dd-total">
                {fmt(data.total_profit_usdt)} USDT
              </span>
            </div>

            {empty && (
              <div
                className="text-sm text-neutral-500 py-6 text-center border border-white/5 bg-black/20"
                data-testid="dd-empty"
              >
                {t("admin.revenue.ddEmpty")}
              </div>
            )}

            {data.orders?.length > 0 && (
              <Section
                icon={ArrowRightLeft}
                title={t("admin.revenue.ddOrdersSection")}
                count={data.orders.length}
                subtotal={`${fmt(data.p2p_profit_usdt)} USDT`}
                testid="dd-orders"
              >
                <DetailTable
                  headers={[t("admin.revenue.colPair"), t("admin.revenue.ddClient"), t("admin.revenue.ddSends"), t("admin.revenue.ddReceives"), t("admin.revenue.ddProfit")]}
                  rows={data.orders.map((o) => ({
                    key: o.id,
                    cells: [
                      <span key="pair" className="text-[#A78BFA]">{o.pair}</span>,
                      o.user_name,
                      `${fmt(o.amount_from)} ${o.from_code}`,
                      `${fmt(o.amount_to)} ${o.to_code}`,
                      <Profit key="profit" v={o.profit_usdt} fmt={fmt} />,
                    ],
                  }))}
                />
              </Section>
            )}

            {data.vip_batch_items?.length > 0 && (
              <Section
                icon={Layers}
                title={t("admin.revenue.ddVipSection")}
                count={data.vip_batch_items.length}
                subtotal={`${fmt(data.vip_batches_profit_usdt)} USDT`}
                testid="dd-vip"
              >
                <DetailTable
                  headers={[t("admin.revenue.ddClient"), t("admin.revenue.ddCardHolder"), t("admin.revenue.colPair"), t("admin.revenue.ddSends"), t("admin.revenue.ddReceives"), t("admin.revenue.ddMargin")]}
                  rows={data.vip_batch_items.map((it) => ({
                    key: it.id,
                    cells: [
                      it.vip_name,
                      <span key="holder" className="font-mono">{it.holder}</span>,
                      <span key="pair" className="text-[#A78BFA]">{it.pair}</span>,
                      `${fmt(it.amount)} ${it.from_code || ""}`,
                      it.amount_to != null ? `${fmt(it.amount_to)} ${it.to_code || ""}` : "—",
                      <Profit key="profit" v={it.margin_usdt} fmt={fmt} />,
                    ],
                  }))}
                />
              </Section>
            )}

            {data.marketplace?.length > 0 && (
              <Section
                icon={ShoppingBag}
                title={t("admin.revenue.ddMarketplaceSection")}
                count={data.marketplace.length}
                subtotal={`${fmt(data.marketplace_profit_usdt)} USDT`}
                testid="dd-marketplace"
              >
                <DetailTable
                  headers={[t("admin.revenue.ddProduct"), t("admin.revenue.ddClient"), t("admin.revenue.ddQty"), t("admin.revenue.ddSale"), t("admin.revenue.ddCost"), t("admin.revenue.ddProfit")]}
                  rows={data.marketplace.map((m) => ({
                    key: m.id,
                    cells: [
                      m.product_name,
                      m.user_name,
                      m.quantity,
                      `${fmt(m.total_usd)} USD`,
                      `${fmt(m.cost_usd)} USD`,
                      <Profit key="profit" v={m.profit_usdt} fmt={fmt} />,
                    ],
                  }))}
                />
              </Section>
            )}

            {data.conversions?.length > 0 && (
              <Section
                icon={Percent}
                title={t("admin.revenue.ddFeesSection")}
                count={data.conversions.length}
                subtotal={`${fmt(data.conversion_fees_usdt)} USDT`}
                testid="dd-fees"
              >
                <DetailTable
                  headers={[t("admin.revenue.ddTime"), t("admin.revenue.ddClient"), t("admin.revenue.colPair"), t("admin.revenue.ddSends"), t("admin.revenue.ddFee")]}
                  rows={data.conversions.map((c, i) => ({
                    key: `${c.created_at}-${i}`,
                    cells: [
                      new Date(c.created_at).toLocaleTimeString(),
                      c.user,
                      <span key="pair" className="text-[#A78BFA]">{c.pair}</span>,
                      c.amount_from != null ? fmt(c.amount_from) : "—",
                      <Profit key="fee" v={c.fee_usdt} fmt={fmt} />,
                    ],
                  }))}
                />
              </Section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({ icon: Icon, title, count, subtotal, testid, children }) {
  return (
    <div className="border border-white/5 bg-black/20" data-testid={testid}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/5">
        <span className="micro-label text-neutral-400 flex items-center gap-2">
          <Icon className="w-4 h-4 text-[#8B5CF6]" />
          {title}
          <span className="text-neutral-600 font-mono">({count})</span>
        </span>
        <span className="font-mono text-sm text-[#22C55E]">{subtotal}</span>
      </div>
      <div className="overflow-x-auto max-h-[300px] tx-body-scroll">
        {children}
      </div>
    </div>
  );
}

function DetailTable({ headers, rows }) {
  return (
    <table className="w-full text-sm">
      <thead className="bg-[#0a0a0a] sticky top-0">
        <tr className="text-left">
          {headers.map((h, i) => (
            <th key={h} className={`px-3 py-2 micro-label text-neutral-500 whitespace-nowrap ${i === headers.length - 1 ? "text-right" : ""}`}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ key, cells }) => (
          <tr key={key} className="border-b border-white/5">
            {cells.map((c, ci) => (
              <td key={headers[ci] || ci} className={`px-3 py-2 font-mono text-xs text-neutral-300 whitespace-nowrap ${ci === cells.length - 1 ? "text-right" : ""}`}>
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Profit({ v, fmt }) {
  const n = Number(v) || 0;
  return (
    <span className={`font-semibold ${n >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}`}>
      {fmt(n)} USDT
    </span>
  );
}
