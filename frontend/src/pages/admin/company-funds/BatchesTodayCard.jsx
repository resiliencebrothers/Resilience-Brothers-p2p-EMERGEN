import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Layers } from "lucide-react";
import { Input } from "@/components/ui/input";
import BatchesDayDetailDialog from "./BatchesDayDetailDialog";

const fmt = (n) =>
  Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const todayStr = () => new Date().toISOString().slice(0, 10);

export default function BatchesTodayCard() {
  const { t } = useTranslation();
  const [date, setDate] = useState(todayStr());
  const [data, setData] = useState(null);
  const [detailDate, setDetailDate] = useState(null);

  useEffect(() => {
    let ignore = false;
    axios.get(`${API}/admin/company-funds/batches-today`, {
      params: { date }, withCredentials: true,
    })
      .then((r) => { if (!ignore) setData(r.data); })
      .catch(() => { if (!ignore) setData(null); });
    return () => { ignore = true; };
  }, [date]);

  if (!data) return null;
  const isToday = date === todayStr();
  return (
    <div className="tactile-card p-5" data-testid="batches-today-card">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <span className="micro-label text-neutral-500 flex items-center gap-2">
          <Layers className="w-4 h-4 text-[#8B5CF6]" />
          {t("admin.companyFunds.batchesToday.title")}
        </span>
        <div className="flex items-center gap-2">
          <Input
            type="date"
            value={date}
            max={todayStr()}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            data-testid="batches-today-date"
            className="w-[160px] rounded-none bg-black/40 border-white/10 text-white h-8 text-xs font-mono"
          />
          {!isToday && (
            <button
              type="button"
              onClick={() => setDate(todayStr())}
              data-testid="batches-today-reset"
              className="text-xs text-[#A78BFA] hover:text-white transition-colors"
            >
              {t("admin.companyFunds.batchesToday.todayBtn")}
            </button>
          )}
        </div>
      </div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setDetailDate(date)}
        onKeyDown={(e) => e.key === "Enter" && setDetailDate(date)}
        data-testid="batches-today-open"
        className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4 cursor-pointer -mx-2 px-2 py-2 hover:bg-[#8B5CF6]/5 transition-colors"
      >
        <div>
          <div className="micro-label text-neutral-500">{t("admin.companyFunds.batchesToday.closed")}</div>
          <div className="font-mono text-2xl text-white mt-1" data-testid="batches-today-closed">
            {data.closed_count}
            {data.auto_count > 0 && (
              <span className="text-[0.6rem] text-[#A78BFA] ml-2 border border-[#A78BFA]/40 px-1.5 py-0.5 uppercase tracking-widest align-middle">
                {data.auto_count} auto
              </span>
            )}
          </div>
        </div>
        <div>
          <div className="micro-label text-neutral-500">{t("admin.companyFunds.batchesToday.orders")}</div>
          <div className="font-mono text-2xl text-white mt-1" data-testid="batches-today-orders">
            {data.orders_approved}
          </div>
        </div>
        <div>
          <div className="micro-label text-neutral-500">{t("admin.companyFunds.batchesToday.volume")}</div>
          <div className="font-mono text-2xl text-[#22C55E] mt-1" data-testid="batches-today-volume">
            {fmt(data.volume_usdt)}
            <span className="text-[0.65rem] text-neutral-500 ml-2">USDT</span>
          </div>
        </div>
      </div>
      <div className="text-[0.65rem] text-[#A78BFA]/80 mt-2">
        {t("admin.companyFunds.batchesToday.clickHint")}
      </div>
      <BatchesDayDetailDialog date={detailDate} onClose={() => setDetailDate(null)} />
    </div>
  );
}
