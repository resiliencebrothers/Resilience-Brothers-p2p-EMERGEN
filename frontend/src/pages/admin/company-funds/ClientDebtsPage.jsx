/**
 * iter162 — Client debts report (full page).
 * Reachable from "Fondo Empresa" → button "Deudas con clientes".
 * Backend: GET /admin/company-funds/client-debts
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Scale, ArrowDownLeft, ArrowUpRight, AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import AdminPageHeader from "@/components/AdminPageHeader";
import { useLiveRefresh } from "@/hooks/useLiveStream";
import { API } from "@/App";

const fmt2 = (n) =>
  Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtAmt = (n) =>
  Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });

const SummaryCard = ({ testid, icon: Icon, label, value, tone, hint }) => (
  <div className="tactile-card p-5" data-testid={testid}>
    <div className="flex items-center gap-2 text-neutral-400 text-xs uppercase tracking-wider mb-2">
      <Icon className={`w-4 h-4 ${tone}`} /> {label}
    </div>
    <div className={`font-mono text-2xl sm:text-3xl break-words ${tone}`}>{value}</div>
    {hint && <div className="text-[11px] text-neutral-500 mt-1">{hint}</div>}
  </div>
);

const DebtTable = ({ testid, title, rows, emptyText, t }) => (
  <div className="tactile-card p-0 overflow-hidden" data-testid={testid}>
    <div className="px-4 py-3 border-b border-white/10 font-medium text-sm">{title}</div>
    {rows.length === 0 ? (
      <div className="px-4 py-6 text-sm text-neutral-500" data-testid={`${testid}-empty`}>{emptyText}</div>
    ) : (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-neutral-500 text-xs uppercase tracking-wider">
              <th className="px-4 py-2">{t("admin.clientDebts.colClient")}</th>
              <th className="px-4 py-2">{t("admin.clientDebts.colBalances")}</th>
              <th className="px-4 py-2 text-right">{t("admin.clientDebts.colTotal")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.user_id} className="border-t border-white/5" data-testid={`${testid}-row-${r.user_id}`}>
                <td className="px-4 py-3 align-top">
                  <div className="text-white">{r.name || "—"}</div>
                  <div className="text-xs text-neutral-500">{r.email}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    {r.balances.map((b) => (
                      <span
                        key={b.currency}
                        className="inline-flex items-center gap-1 border border-white/10 bg-white/[0.03] px-2 py-0.5 font-mono text-xs"
                      >
                        {fmtAmt(b.amount)} {b.currency}
                        {b.usdt !== null && b.currency !== "USDT" && (
                          <span className="text-neutral-500">≈ {fmt2(b.usdt)} USDT</span>
                        )}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-right font-mono whitespace-nowrap text-white">
                  {fmt2(r.total_usdt)} <span className="text-neutral-500 text-xs">USDT</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </div>
);

export default function ClientDebtsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/company-funds/client-debts`, { withCredentials: true });
      setData(r.data);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveRefresh(load, ["ledger_changed", "vip_batch_item_decision", "balance_updated"]);

  const netTone = (data?.net_usdt || 0) >= 0 ? "text-[#22C55E]" : "text-[#F87171]";
  const missing = data?.missing_rate_currencies || [];

  return (
    <div className="space-y-6" data-testid="client-debts-page">
      <button
        type="button"
        data-testid="client-debts-back"
        onClick={() => navigate("/admin/company-funds")}
        className="flex items-center gap-2 text-sm text-neutral-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> {t("admin.clientDebts.back")}
      </button>

      <AdminPageHeader
        eyebrow={t("admin.clientDebts.eyebrow")}
        title={t("admin.clientDebts.title")}
        subtitle={t("admin.clientDebts.subtitle")}
        icon={Scale}
        testid="client-debts-header"
        actions={
          <Button
            data-testid="client-debts-refresh"
            variant="outline"
            onClick={load}
            className="border-white/10 bg-transparent text-neutral-300 hover:bg-white/5 rounded-none"
          >
            <RefreshCw className="w-4 h-4 mr-2" /> {t("admin.clientDebts.refresh")}
          </Button>
        }
      />

      {loading && (
        <div className="tactile-card p-6 animate-pulse" data-testid="client-debts-loading">
          <div className="h-4 w-48 bg-white/5 mb-3" />
          <div className="h-8 w-72 bg-white/10" />
        </div>
      )}

      {!loading && error && (
        <div className="tactile-card p-6 text-sm text-[#F87171]" data-testid="client-debts-error">
          <AlertTriangle className="w-4 h-4 inline mr-2" />
          {t("admin.clientDebts.loadError")}
        </div>
      )}

      {!loading && !error && data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <SummaryCard
              testid="debts-summary-owe-us"
              icon={ArrowDownLeft}
              label={t("admin.clientDebts.oweUs")}
              value={`${fmt2(data.total_owe_us_usdt)} USDT`}
              tone="text-[#22C55E]"
            />
            <SummaryCard
              testid="debts-summary-we-owe"
              icon={ArrowUpRight}
              label={t("admin.clientDebts.weOwe")}
              value={`${fmt2(data.total_we_owe_usdt)} USDT`}
              tone="text-[#F87171]"
            />
            <SummaryCard
              testid="debts-summary-net"
              icon={Scale}
              label={t("admin.clientDebts.net")}
              value={`${data.net_usdt >= 0 ? "+" : ""}${fmt2(data.net_usdt)} USDT`}
              tone={netTone}
              hint={t("admin.clientDebts.netHint")}
            />
          </div>

          {missing.length > 0 && (
            <div
              className="flex items-center gap-2 text-xs text-amber-400/90 border border-amber-500/20 bg-amber-500/5 px-3 py-2"
              data-testid="client-debts-missing-rates"
            >
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {t("admin.clientDebts.missingRates", { codes: missing.join(", ") })}
            </div>
          )}

          <DebtTable
            testid="owe-us-table"
            title={t("admin.clientDebts.oweUsTable")}
            rows={data.owe_us}
            emptyText={t("admin.clientDebts.emptyOweUs")}
            t={t}
          />

          <DebtTable
            testid="we-owe-table"
            title={t("admin.clientDebts.weOweTable")}
            rows={data.we_owe}
            emptyText={t("admin.clientDebts.emptyWeOwe")}
            t={t}
          />
        </>
      )}
    </div>
  );
}
