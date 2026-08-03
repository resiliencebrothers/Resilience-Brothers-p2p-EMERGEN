import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Check, X as XIcon, Clock, ExternalLink, Truck, Building2 } from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";

/**
 * iter113 — Admin queue for client deposits (`deposits` collection).
 * Confirming credits the client's per-currency balance.
 */
export default function AdminDeposits({ onChanged }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/deposits`, {
        params: { status: statusFilter, limit: 300 },
        withCredentials: true,
      });
      setItems(r.data?.items || []);
      onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminDeposits.loadError"));
    } finally { setLoading(false); }
  }, [statusFilter, t, onChanged]);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("deposit_created", load);

  const confirm = async (id) => {
    try {
      await axios.post(`${API}/admin/deposits/${id}/confirm`, {}, { withCredentials: true });
      toast.success(t("adminDeposits.confirmedToast"));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminDeposits.actionError"));
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-deposits">
      <div className="flex items-center gap-2 flex-wrap">
        {["pending", "confirmed", "rejected"].map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatusFilter(s)}
            data-testid={`deposits-filter-${s}`}
            className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
              statusFilter === s
                ? "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#8B5CF6]"
                : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
            }`}
          >
            {t(`adminVipLedgerOps.filter.${s}`)}
          </button>
        ))}
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[980px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colClient")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("adminDeposits.colAmount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colMethod")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colProof")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("adminDeposits.colCreated")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colStatus")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminDeposits.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8">{t("admin.common.loadingEllipsis")}</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan="7" className="text-center text-neutral-500 py-8" data-testid="admin-deposits-empty">
                {t("adminDeposits.empty")}
              </td></tr>
            )}
            {!loading && items.map((d) => (
              <tr key={d.id} className="border-b border-white/5" data-testid={`admin-deposit-row-${d.id}`}>
                <td className="px-4 py-3">
                  <div className="text-white text-xs">{d.user_name || "—"}</div>
                  <div className="text-[0.65rem] text-neutral-500 font-mono">{d.user_email}</div>
                  <div className="text-[0.6rem] uppercase text-neutral-600">{d.user_role}</div>
                </td>
                <td className="px-4 py-3 font-mono text-emerald-400 text-right">
                  {Number(d.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  <span className="text-[0.6rem] text-neutral-500 ml-1">{d.currency}</span>
                  {d.usdt_equivalent != null && (
                    <div className="text-[0.6rem] text-neutral-500">≈ {Number(d.usdt_equivalent).toFixed(2)} USDT</div>
                  )}
                </td>
                <td className="px-4 py-3 text-xs">
                  <div className="text-neutral-300 uppercase font-mono">{t(`deposits.method.${d.method}`, d.method)}</div>
                  {d.cash_mode === "courier" && (
                    <div className="mt-1 space-y-0.5 text-[0.65rem] text-amber-400" data-testid={`deposit-courier-${d.id}`}>
                      <div className="flex items-center gap-1"><Truck className="w-3 h-3" /> {t("adminDeposits.courier")}</div>
                      <div className="text-neutral-400">{d.contact_name} · {d.pickup_phone}</div>
                      <div className="text-neutral-500 max-w-[220px]">{d.pickup_address}</div>
                    </div>
                  )}
                  {d.cash_mode === "office" && (
                    <div className="mt-1 flex items-center gap-1 text-[0.65rem] text-[#A78BFA]" data-testid={`deposit-office-${d.id}`}>
                      <Building2 className="w-3 h-3" /> {t("adminDeposits.office")}
                    </div>
                  )}
                  {d.account_holder && (
                    <div className="text-[0.65rem] text-neutral-500 mt-0.5">
                      {t("adminVipLedgerOps.holderLabel")}: <span className="text-neutral-300">{d.account_holder}</span>
                    </div>
                  )}
                  {d.tx_hash && (
                    <div className="text-[0.65rem] text-emerald-400 font-mono mt-0.5 max-w-[200px] truncate" title={d.tx_hash}>
                      {d.tx_hash}
                    </div>
                  )}
                  {d.note && <div className="text-[0.65rem] italic text-neutral-500 mt-0.5 max-w-[220px]">{d.note}</div>}
                </td>
                <td className="px-4 py-3 text-xs">
                  {d.proof_url ? (
                    <a
                      href={d.proof_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-testid={`deposit-proof-link-${d.id}`}
                      className="inline-flex items-center gap-1 text-[#8B5CF6] hover:underline"
                    >
                      {t("adminVipLedgerOps.viewProof")} <ExternalLink className="w-3 h-3" />
                    </a>
                  ) : <span className="text-neutral-600">—</span>}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">
                  {new Date(d.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3"><Pill status={d.status} t={t} /></td>
                <td className="px-4 py-3">
                  {d.status === "pending" ? (
                    <div className="flex gap-2">
                      <Button
                        onClick={() => confirm(d.id)}
                        data-testid={`admin-deposit-confirm-${d.id}`}
                        className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-8 px-3 text-xs font-semibold"
                      >
                        <Check className="w-3 h-3 mr-1" /> {t("adminDeposits.confirm")}
                      </Button>
                      <Button
                        onClick={() => setRejecting(d)}
                        data-testid={`admin-deposit-reject-${d.id}`}
                        variant="ghost"
                        className="rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8 px-3 text-xs"
                      >
                        <XIcon className="w-3 h-3 mr-1" /> {t("adminDeposits.reject")}
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-neutral-500">
                      {d.reviewed_at ? new Date(d.reviewed_at).toLocaleDateString() : "—"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RejectDepositDialog
        deposit={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => { setRejecting(null); load(); }}
      />
    </div>
  );
}


function Pill({ status, t }) {
  const map = {
    pending:   { cls: "border-amber-500/40 bg-amber-500/5 text-amber-400", Icon: Clock },
    confirmed: { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: Check },
    rejected:  { cls: "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]", Icon: XIcon },
  }[status] || {};
  const Icon = map.Icon || Clock;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border font-mono ${map.cls || ""}`}>
      <Icon className="w-3 h-3" /> {t(`deposits.status.${status}`, status)}
    </span>
  );
}


function RejectDepositDialog({ deposit, onClose, onDone }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (deposit) setNote(""); }, [deposit]);

  const submit = async () => {
    if (!deposit) return;
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/deposits/${deposit.id}/reject`,
        { admin_note: note.trim() },
        { withCredentials: true },
      );
      toast.success(t("adminDeposits.rejectedToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminDeposits.actionError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={!!deposit} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="admin-deposit-reject-dialog"
        className="bg-[#0c0c0c] border border-[#EF4444]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("adminDeposits.rejectTitle")}</DialogTitle>
        </DialogHeader>
        <textarea
          data-testid="admin-deposit-reject-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={300}
          placeholder={t("adminDeposits.rejectPlaceholder")}
          className="w-full mt-3 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#EF4444]/50 focus:outline-none"
        />
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            data-testid="admin-deposit-reject-confirm"
            className="rounded-none bg-[#EF4444] hover:bg-[#F87171] text-white disabled:opacity-40"
          >
            {t("adminDeposits.reject")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
