import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { UploadCloud, FileText, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useLiveEvent } from "@/hooks/useLiveStream";

const STATUS_TONE = {
  uploaded: "text-neutral-400 border-white/10",
  processing: "text-sky-400 border-sky-500/40",
  processed: "text-emerald-400 border-emerald-500/40",
  partially_processed: "text-amber-400 border-amber-500/40",
  failed: "text-red-400 border-red-500/40",
};

export const ImportSummaryRow = ({ imp, t }) => (
  <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 text-center text-xs font-mono mt-2">
    {[
      ["detected", imp.total_transactions_detected],
      ["credits", imp.total_credits_detected],
      ["auto", imp.total_auto_matched],
      ["review", imp.total_manual_review],
      ["unmatched", imp.total_unmatched],
      ["duplicates", imp.total_duplicates],
    ].map(([k, v]) => (
      <div key={k} className="border border-white/10 bg-white/[0.02] px-2 py-1.5">
        <div className="text-white text-sm">{v ?? 0}</div>
        <div className="text-neutral-500 text-[10px] uppercase tracking-wider">
          {t(`reconciliation.counts.${k}`)}
        </div>
      </div>
    ))}
  </div>
);

export default function ImportTab({ onProcessed }) {
  const { t } = useTranslation();
  const [accounts, setAccounts] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [accountId, setAccountId] = useState("");
  const [bankName, setBankName] = useState("");
  const [currency, setCurrency] = useState("");
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [lastImport, setLastImport] = useState(null);
  const fileRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => {
    axios.get(`${API}/admin/reconciliation/bank-accounts`, { withCredentials: true })
      .then((r) => setAccounts(r.data?.items || []))
      .catch(() => {});
    axios.get(`${API}/currencies`)
      .then((r) => {
        const seen = new Set();
        const list = (r.data || []).filter((c) => {
          if (!c.is_active || seen.has(c.code)) return false;
          seen.add(c.code);
          return true;
        });
        setCurrencies(list);
      })
      .catch(() => {});
    return () => clearInterval(pollRef.current);
  }, []);

  const pollImport = useCallback((id) => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await axios.get(`${API}/admin/reconciliation/imports/${id}`, { withCredentials: true });
        setLastImport(r.data);
        if (!["uploaded", "processing"].includes(r.data.processing_status)) {
          clearInterval(pollRef.current);
          onProcessed?.();
          if (r.data.processing_status === "failed") {
            toast.error(t("reconciliation.import.failed"));
          } else {
            toast.success(t("reconciliation.import.done", {
              auto: r.data.total_auto_matched, review: r.data.total_manual_review,
            }));
          }
        }
      } catch { /* keep polling */ }
    }, 2500);
  }, [onProcessed, t]);

  useLiveEvent("reconciliation_import", useCallback((ev) => {
    if (lastImport && ev?.import_id === lastImport.id) pollImport(lastImport.id);
  }, [lastImport, pollImport]));

  const onSelectAccount = (id) => {
    setAccountId(id);
    const acc = accounts.find((a) => a.id === id);
    if (acc) {
      setCurrency(acc.currency_code || "");
      if (!bankName) setBankName(acc.label?.split("·")[0]?.trim() || "");
    }
  };

  const submit = async () => {
    if (!file || !bankName.trim() || !currency.trim()) {
      toast.error(t("reconciliation.import.missingFields"));
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("bank_account_id", accountId || "");
      fd.append("bank_name", bankName.trim());
      fd.append("currency", currency.trim().toUpperCase());
      const r = await axios.post(`${API}/admin/reconciliation/imports`, fd, { withCredentials: true });
      setLastImport(r.data);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      toast.success(t("reconciliation.import.uploaded"));
      pollImport(r.data.id);
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("reconciliation.import.error"));
    } finally {
      setUploading(false);
    }
  };

  const processing = lastImport && ["uploaded", "processing"].includes(lastImport.processing_status);

  return (
    <div className="space-y-5" data-testid="reconciliation-import-tab">
      <div className="tactile-card p-5 space-y-4 max-w-2xl">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs text-neutral-400 uppercase tracking-wider">
              {t("reconciliation.import.account")}
            </label>
            <Select value={accountId} onValueChange={onSelectAccount}>
              <SelectTrigger data-testid="recon-account-select" className="rounded-none bg-[#0a0a0a] border-white/10">
                <SelectValue placeholder={t("reconciliation.import.accountPh")} />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.label} ({a.currency_code})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-neutral-400 uppercase tracking-wider">
              {t("reconciliation.import.currency")}
            </label>
            <Select value={currency} onValueChange={setCurrency}>
              <SelectTrigger data-testid="recon-currency-select" className="rounded-none bg-[#0a0a0a] border-white/10 font-mono">
                <SelectValue placeholder={t("reconciliation.import.currencyPh")} />
              </SelectTrigger>
              <SelectContent>
                {currencies.map((c) => (
                  <SelectItem key={c.id || c.code} value={c.code}>
                    {c.code} — {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-neutral-400 uppercase tracking-wider">
            {t("reconciliation.import.bank")}
          </label>
          <Input
            data-testid="recon-bank-input"
            value={bankName}
            onChange={(e) => setBankName(e.target.value)}
            placeholder={t("reconciliation.import.bankPh")}
            className="rounded-none bg-[#0a0a0a] border-white/10"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs text-neutral-400 uppercase tracking-wider">
            {t("reconciliation.import.file")}
          </label>
          <input
            ref={fileRef}
            data-testid="recon-file-input"
            type="file"
            accept=".csv,.xls,.xlsx,.pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm text-neutral-400 file:mr-3 file:px-3 file:py-1.5 file:border file:border-white/10 file:bg-white/5 file:text-white file:text-xs file:cursor-pointer file:rounded-none bg-[#0a0a0a] border border-white/10 p-2"
          />
          <p className="text-[11px] text-neutral-500">{t("reconciliation.import.fileHint")}</p>
        </div>
        <Button
          data-testid="recon-upload-btn"
          onClick={submit}
          disabled={uploading || !file}
          className="rounded-none bg-violet-600 hover:bg-violet-500 text-white"
        >
          {uploading
            ? <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            : <UploadCloud className="w-4 h-4 mr-2" />}
          {t("reconciliation.import.submit")}
        </Button>
      </div>

      {lastImport && (
        <div className="tactile-card p-5 max-w-2xl" data-testid="recon-last-import">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2 text-sm">
              <FileText className="w-4 h-4 text-neutral-400" />
              <span className="text-white">{lastImport.original_file_name}</span>
            </div>
            <span
              data-testid="recon-import-status"
              className={`inline-flex items-center gap-1.5 text-xs uppercase tracking-wider px-2 py-1 border font-mono ${STATUS_TONE[lastImport.processing_status] || ""}`}
            >
              {processing && <Loader2 className="w-3 h-3 animate-spin" />}
              {lastImport.processing_status === "processed" && <CheckCircle2 className="w-3 h-3" />}
              {lastImport.processing_status === "failed" && <AlertTriangle className="w-3 h-3" />}
              {t(`reconciliation.status.${lastImport.processing_status}`)}
              {processing && lastImport.processing_stage && (
                <span className="text-neutral-500 normal-case">
                  · {t(`reconciliation.stage.${lastImport.processing_stage}`)}
                </span>
              )}
            </span>
          </div>
          {lastImport.notes && (
            <p className="text-xs text-red-400 mt-2">{lastImport.notes}</p>
          )}
          {!processing && <ImportSummaryRow imp={lastImport} t={t} />}
        </div>
      )}
    </div>
  );
}
