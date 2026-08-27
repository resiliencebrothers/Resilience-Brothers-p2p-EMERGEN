import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { TopScrollTable } from "@/components/TopScrollTable";

const WINDOWS = [7, 30, 90, 365];

const STATUS_TONE = {
  auto_matched: "text-emerald-400",
  manual_matched: "text-emerald-300",
  manual_review: "text-amber-400",
  unmatched: "text-neutral-300",
  duplicate: "text-sky-400",
  error: "text-red-400",
  ignored: "text-neutral-500",
};

const Kpi = ({ label, value, tone = "text-white", testid, onClick }) => (
  <div
    className={`border border-white/10 bg-white/[0.02] p-4 min-w-0 overflow-hidden ${
      onClick ? "cursor-pointer transition-colors hover:border-violet-500/50 hover:bg-white/[0.05]" : ""
    }`}
    data-testid={testid}
    onClick={onClick}
    role={onClick ? "button" : undefined}
  >
    <div className={`text-2xl font-mono truncate ${tone}`}>{value}</div>
    <div className="text-[11px] uppercase tracking-wider text-neutral-500 mt-1 break-words">{label}</div>
  </div>
);

const Th = ({ children, right }) => (
  <th className={`px-3 py-2 text-xs uppercase tracking-wider text-neutral-500 ${right ? "text-right" : "text-left"}`}>
    {children}
  </th>
);

function DetailRows({ data, t }) {
  if (data.kind === "audit") {
    return (
      <table className="w-full text-sm">
        <thead><tr>
          <Th>{t("reconciliation.dash.colDate")}</Th>
          <Th>{t("reconciliation.dash.colOrder")}</Th>
          <Th>{t("reconciliation.dash.colBy")}</Th>
        </tr></thead>
        <tbody>
          {data.items.map((r) => (
            <tr key={r.id} className="border-t border-white/5" data-testid="recon-detail-row">
              <td className="px-3 py-2 font-mono text-neutral-300">{String(r.performed_at || "").slice(0, 16).replace("T", " ")}</td>
              <td className="px-3 py-2 font-mono text-white">{(r.order_id || "—").slice(0, 12)}</td>
              <td className="px-3 py-2 text-neutral-300">{r.performed_by_name || r.performed_by || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (data.kind === "imports") {
    return (
      <table className="w-full text-sm">
        <thead><tr>
          <Th>{t("reconciliation.dash.colDate")}</Th>
          <Th>{t("reconciliation.dash.colFile")}</Th>
          <Th right>{t("reconciliation.dash.colDetected")}</Th>
          <Th right>{t("reconciliation.dash.colResults")}</Th>
        </tr></thead>
        <tbody>
          {data.items.map((r) => (
            <tr key={r.id} className="border-t border-white/5" data-testid="recon-detail-row">
              <td className="px-3 py-2 font-mono text-neutral-300">{String(r.uploaded_at || "").slice(0, 10)}</td>
              <td className="px-3 py-2 text-white break-all">{r.original_file_name} <span className="text-neutral-500">· {r.currency}</span></td>
              <td className="px-3 py-2 text-right font-mono text-neutral-300">{r.total_transactions_detected ?? 0}</td>
              <td className="px-3 py-2 text-right font-mono">
                <span className="text-emerald-400">{r.total_auto_matched ?? 0}</span>
                <span className="text-neutral-600"> / </span>
                <span className="text-amber-400">{r.total_manual_review ?? 0}</span>
                <span className="text-neutral-600"> / </span>
                <span className="text-neutral-300">{r.total_unmatched ?? 0}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return (
    <table className="w-full text-sm">
      <thead><tr>
        <Th>{t("reconciliation.dash.colDate")}</Th>
        <Th>{t("reconciliation.dash.colSender")}</Th>
        <Th right>{t("reconciliation.dash.colAmount")}</Th>
        <Th>{t("reconciliation.dash.colStatus")}</Th>
        <Th right>{t("reconciliation.dash.colScore")}</Th>
      </tr></thead>
      <tbody>
        {data.items.map((r) => (
          <tr key={r.id} className="border-t border-white/5" data-testid="recon-detail-row">
            <td className="px-3 py-2 font-mono text-neutral-300">{String(r.transaction_date || "").slice(0, 10)}</td>
            <td className="px-3 py-2 text-white">
              <div className="truncate max-w-[220px]">{r.sender_name || "—"}</div>
              {r.description && (
                <div className="text-[11px] text-neutral-500 truncate max-w-[220px]">{r.description}</div>
              )}
            </td>
            <td className="px-3 py-2 text-right font-mono text-white">
              {Number(r.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })} <span className="text-neutral-500">{r.currency}</span>
            </td>
            <td className={`px-3 py-2 text-xs uppercase tracking-wider ${STATUS_TONE[r.status] || "text-neutral-300"}`}>
              {t(`reconciliation.dash.statuses.${r.status}`, r.status)}
            </td>
            <td className="px-3 py-2 text-right font-mono text-neutral-300">{r.confidence_score ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DetailDialog({ detail, days, currency, onClose }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!detail) return;
    setLoading(true);
    setData(null);
    const params = { bucket: detail.bucket, days };
    if (currency) params.currency = currency;
    axios.get(`${API}/admin/reconciliation/dashboard/details`, {
      params, withCredentials: true,
    })
      .then((r) => setData(r.data))
      .catch((err) => toast.error(err?.response?.data?.detail || "Error"))
      .finally(() => setLoading(false));
  }, [detail, days, currency]);

  return (
    <Dialog open={!!detail} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none bg-neutral-950 border-white/10 max-w-3xl max-h-[80vh] overflow-y-auto" data-testid="recon-detail-dialog">
        <DialogHeader>
          <DialogTitle className="text-white font-mono text-base">
            {detail?.label} — {t("reconciliation.dash.days", { n: days })}
          </DialogTitle>
        </DialogHeader>
        {loading ? (
          <div className="p-6 text-sm text-neutral-500 animate-pulse">…</div>
        ) : !data || (data.items || []).length === 0 ? (
          <div className="p-6 text-sm text-neutral-500" data-testid="recon-detail-empty">
            {t("reconciliation.dash.detailEmpty")}
          </div>
        ) : (
          <TopScrollTable
            testid="recon-detail"
            deps={[data]}
            maxHeightClass="max-h-[65vh]"
          >
            <DetailRows data={data} t={t} />
          </TopScrollTable>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function DashboardTab({ currency }) {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { days };
      if (currency) params.currency = currency;
      const r = await axios.get(`${API}/admin/reconciliation/dashboard`, {
        params, withCredentials: true,
      });
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    } finally { setLoading(false); }
  }, [days, currency]);

  useEffect(() => { load(); }, [load]);

  const c = data?.counts || {};
  const open = (bucket, labelKey) => setDetail({ bucket, label: t(labelKey) });

  return (
    <div className="space-y-4" data-testid="reconciliation-dashboard-tab">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          {WINDOWS.map((d) => (
            <button
              key={d}
              type="button"
              data-testid={`recon-dash-days-${d}`}
              onClick={() => setDays(d)}
              className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
                days === d
                  ? "bg-violet-500/10 border-violet-500 text-violet-300"
                  : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
              }`}
            >
              {t("reconciliation.dash.days", { n: d })}
            </button>
          ))}
        </div>
        <Button variant="outline" onClick={load} data-testid="recon-dash-refresh"
          className="rounded-none border-white/10 text-neutral-300 hover:bg-white/5 h-8 text-xs">
          <RefreshCw className="w-3.5 h-3.5 mr-2" /> {t("reconciliation.history.refresh")}
        </Button>
      </div>

      {loading || !data ? (
        <div className="tactile-card p-6 text-sm text-neutral-500 animate-pulse">…</div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <Kpi label={t("reconciliation.dash.importsToday")} value={data.today?.imports ?? 0} testid="recon-dash-imports-today" />
            <Kpi label={t("reconciliation.dash.txToday")} value={data.today?.transactions ?? 0} testid="recon-dash-tx-today" />
            <Kpi label={t("reconciliation.dash.autoRate")} value={`${data.auto_match_rate}%`}
              tone="text-emerald-400" testid="recon-dash-auto-rate" />
            <Kpi label={t("reconciliation.dash.avgScore")} value={data.avg_score_matched || "—"}
              tone="text-violet-300" testid="recon-dash-avg-score" />
            <Kpi label={t("reconciliation.dash.avgProcessing")}
              value={data.avg_processing_seconds ? `${data.avg_processing_seconds}s` : "—"}
              testid="recon-dash-avg-processing" />
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <Kpi label={t("reconciliation.dash.reconciled")} value={data.reconciled ?? 0}
              tone="text-emerald-400" testid="recon-dash-reconciled"
              onClick={() => open("reconciled", "reconciliation.dash.reconciled")} />
            <Kpi label={t("reconciliation.dash.review")} value={c.manual_review ?? 0}
              tone="text-amber-400" testid="recon-dash-review"
              onClick={() => open("manual_review", "reconciliation.dash.review")} />
            <Kpi label={t("reconciliation.dash.unmatched")} value={c.unmatched ?? 0}
              tone="text-neutral-300" testid="recon-dash-unmatched"
              onClick={() => open("unmatched", "reconciliation.dash.unmatched")} />
            <Kpi label={t("reconciliation.dash.duplicates")} value={c.duplicate ?? 0}
              tone="text-sky-400" testid="recon-dash-duplicates"
              onClick={() => open("duplicate", "reconciliation.dash.duplicates")} />
            <Kpi label={t("reconciliation.dash.errors")} value={c.error ?? 0}
              tone={c.error ? "text-red-400" : "text-white"} testid="recon-dash-errors"
              onClick={() => open("error", "reconciliation.dash.errors")} />
            <Kpi label={t("reconciliation.dash.rollbacks")} value={data.rollbacks ?? 0}
              tone={data.rollbacks ? "text-red-400" : "text-white"} testid="recon-dash-rollbacks"
              onClick={() => open("rollbacks", "reconciliation.dash.rollbacks")} />
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <Kpi label={t("reconciliation.dash.importsWindow")} value={data.imports_window ?? 0}
              testid="recon-dash-imports-window"
              onClick={() => open("imports", "reconciliation.dash.importsWindow")} />
            <Kpi label={t("reconciliation.dash.ocrRate")} value={`${data.ocr_usage_rate}%`} testid="recon-dash-ocr-rate" />
            <Kpi label={t("reconciliation.dash.parserErrorRate")} value={`${data.parser_error_rate}%`} testid="recon-dash-parser-errors" />
          </div>

          <div className="tactile-card p-0 overflow-hidden" data-testid="recon-dash-currency-table">
            <div className="px-4 py-3 border-b border-white/10 text-sm text-white">
              {t("reconciliation.dash.byCurrency")}
            </div>
            {(data.reconciled_by_currency || []).length === 0 ? (
              <div className="p-5 text-sm text-neutral-500" data-testid="recon-dash-currency-empty">
                {t("reconciliation.dash.empty")}
              </div>
            ) : (
              <TopScrollTable
                testid="recon-dash-currency"
                deps={[data.reconciled_by_currency]}
                maxHeightClass="max-h-[50vh]"
              >
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-neutral-500 text-xs uppercase tracking-wider">
                      <th className="px-4 py-2">{t("reconciliation.dash.colCurrency")}</th>
                      <th className="px-4 py-2 text-right">{t("reconciliation.dash.colTotal")}</th>
                      <th className="px-4 py-2 text-right">{t("reconciliation.dash.colCount")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.reconciled_by_currency.map((r) => (
                      <tr key={r.currency} className="border-t border-white/5"
                        data-testid={`recon-dash-currency-${r.currency}`}>
                        <td className="px-4 py-2.5 font-mono text-white">{r.currency}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-emerald-400">
                          {Number(r.total).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-neutral-300">{r.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TopScrollTable>
            )}
          </div>
        </>
      )}
      <DetailDialog detail={detail} days={days} currency={currency} onClose={() => setDetail(null)} />
    </div>
  );
}
