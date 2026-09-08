import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

// iter233 — reporte mensual: entradas y salidas por día.
export function ReportPanel({ box, fund }) {
  const { t } = useTranslation();
  const [month, setMonth] = useState(thisMonth());
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!box || !month) return;
    axios.get(`${API}/cashbox/boxes/${box.id}/reporte`,
      { params: { fund, month }, withCredentials: true })
      .then((r) => setData(r.data)).catch(() => setData(null));
  }, [box, fund, month]);

  return (
    <div className="tactile-card p-4 space-y-3" data-testid="cashbox-report-panel">
      <div className="flex items-center gap-3 flex-wrap">
        <p className="micro-label text-neutral-500">{t("cashbox.reportTitle")}</p>
        <Input data-testid="report-month" type="month" value={month}
          onChange={(e) => e.target.value && setMonth(e.target.value)}
          className="rounded-none h-9 bg-[#0a0a0a] border-white/10 font-mono w-[170px]" />
      </div>
      {!data || data.days.length === 0 ? (
        <p className="text-sm text-neutral-500 py-4 text-center" data-testid="report-empty">{t("cashbox.reportEmpty")}</p>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left micro-label text-neutral-500 border-b border-white/10">
                <th className="py-1.5">{t("cashbox.reportDay")}</th>
                <th className="text-right">{t("cashbox.entradas")}</th>
                <th className="text-right">{t("cashbox.salidas")}</th>
                <th className="text-right">{t("cashbox.neto")}</th>
              </tr>
            </thead>
            <tbody>
              {data.days.map((r) => (
                <tr key={r.date} className="border-b border-white/5 font-mono" data-testid={`report-row-${r.date}`}>
                  <td className="py-1.5">{r.date}</td>
                  <td className="text-right text-emerald-400">{fmt(r.entradas)}</td>
                  <td className="text-right text-red-400">{fmt(r.salidas)}</td>
                  <td className={`text-right ${r.neto >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(r.neto)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="font-mono font-bold border-t border-white/15" data-testid="report-totals">
                <td className="py-1.5">{t("cashbox.reportTotal")}</td>
                <td className="text-right text-emerald-400">{fmt(data.total_entradas)}</td>
                <td className="text-right text-red-400">{fmt(data.total_salidas)}</td>
                <td className={`text-right ${data.neto >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(data.neto)}</td>
              </tr>
            </tfoot>
          </table>
        </>
      )}
    </div>
  );
}
