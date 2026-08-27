import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Download, RefreshCw, RotateCcw, Loader2 } from "lucide-react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { ImportSummaryRow } from "./ImportTab";

const STATUS_TONE = {
  uploaded: "text-neutral-400 border-white/10",
  processing: "text-sky-400 border-sky-500/40",
  processed: "text-emerald-400 border-emerald-500/40",
  partially_processed: "text-amber-400 border-amber-500/40",
  failed: "text-red-400 border-red-500/40",
};

export default function HistoryTab({ currency }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);
  const [reprocessing, setReprocessing] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 200 };
      if (currency) params.currency = currency;
      const r = await axios.get(`${API}/admin/reconciliation/imports`, {
        params, withCredentials: true,
      });
      setItems(r.data?.items || []);
    } catch { /* noop */ } finally { setLoading(false); }
  }, [currency]);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("reconciliation_import", load);

  const reprocess = async (imp) => {
    setReprocessing(imp.id);
    try {
      await axios.post(`${API}/admin/reconciliation/imports/${imp.id}/reprocess`,
        {}, { withCredentials: true });
      toast.success(t("reconciliation.history.reprocessStarted"));
      setTimeout(load, 1200);
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("reconciliation.history.reprocessError"));
    } finally { setReprocessing(null); }
  };

  const download = async (imp) => {
    const res = await axios.get(`${API}/admin/reconciliation/imports/${imp.id}/file`, {
      responseType: "blob", withCredentials: true,
    });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url; a.download = imp.original_file_name; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-3" data-testid="reconciliation-history-tab">
      <div className="flex justify-end">
        <Button variant="outline" onClick={load} data-testid="recon-history-refresh"
          className="rounded-none border-white/10 text-neutral-300 hover:bg-white/5 h-8 text-xs">
          <RefreshCw className="w-3.5 h-3.5 mr-2" /> {t("reconciliation.history.refresh")}
        </Button>
      </div>
      {loading ? (
        <div className="tactile-card p-6 text-sm text-neutral-500 animate-pulse">…</div>
      ) : items.length === 0 ? (
        <div className="tactile-card p-6 text-sm text-neutral-500" data-testid="recon-history-empty">
          {t("reconciliation.history.empty")}
        </div>
      ) : items.map((imp) => (
        <div key={imp.id} className="tactile-card p-4" data-testid={`recon-import-${imp.id}`}>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <button
                type="button"
                onClick={() => setExpanded(expanded === imp.id ? null : imp.id)}
                className="text-white text-sm hover:text-violet-300 transition-colors"
                data-testid={`recon-import-toggle-${imp.id}`}
              >
                {imp.original_file_name}
              </button>
              <div className="text-xs text-neutral-500 font-mono mt-0.5">
                {imp.bank_name} · {imp.currency} · {String(imp.uploaded_at).slice(0, 16).replace("T", " ")}
                {imp.uploaded_by_name ? ` · ${imp.uploaded_by_name}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs uppercase tracking-wider px-2 py-1 border font-mono ${STATUS_TONE[imp.processing_status] || ""}`}>
                {t(`reconciliation.status.${imp.processing_status}`)}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => reprocess(imp)}
                disabled={reprocessing === imp.id
                  || ["uploaded", "processing"].includes(imp.processing_status)}
                data-testid={`recon-reprocess-${imp.id}`}
                title={t("reconciliation.history.reprocess")}
                className="rounded-none h-7 border-white/10 text-neutral-300 hover:bg-white/5"
              >
                {reprocessing === imp.id
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <RotateCcw className="w-3.5 h-3.5" />}
                <span className="ml-1.5 hidden sm:inline text-xs">
                  {t("reconciliation.history.reprocess")}
                </span>
              </Button>
              <Button size="sm" variant="outline" onClick={() => download(imp)}
                data-testid={`recon-download-${imp.id}`}
                className="rounded-none h-7 border-white/10 text-neutral-300 hover:bg-white/5">
                <Download className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
          {expanded === imp.id && <ImportSummaryRow imp={imp} t={t} />}
          {imp.notes && (
            <p
              className="text-xs text-amber-400 mt-2 border border-amber-500/20 bg-amber-500/5 p-2"
              data-testid={`recon-import-notes-${imp.id}`}
            >
              {imp.notes}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
