import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Coins, HandCoins, Check, X as XIcon, Clock, Plus, ExternalLink, FileDown, Mail, AlertTriangle,
} from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";
import CopyableText from "@/components/CopyableText";
import { EmailLedgerDialog } from "@/pages/dashboard/vip/VipLedgerOps";

/**
 * iter110 · Phases 2+3 admin queues — capital deposits + settlements.
 * Rendered by `AdminVipBatches.jsx` when the sub-tab is switched.
 */

const METHODS = [
  { code: "bank_transfer", labelKey: "vipLedgerOps.method.bank_transfer" },
  { code: "crypto",        labelKey: "vipLedgerOps.method.crypto" },
  { code: "zelle",         labelKey: "vipLedgerOps.method.zelle" },
  { code: "cash",          labelKey: "vipLedgerOps.method.cash" },
  { code: "other",         labelKey: "vipLedgerOps.method.other" },
];


export function AdminCapitalDeposits({ onChanged }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState(null);
  const [dupConfirm, setDupConfirm] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/vip-capital-deposits`, {
        params: { status: statusFilter, limit: 300 },
        withCredentials: true,
      });
      setItems(r.data?.items || []);
      onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipLedgerOps.loadError"));
    } finally { setLoading(false); }
  }, [statusFilter, t, onChanged]);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("capital_deposit", load);

  const confirm = async (id, force = false) => {
    try {
      await axios.post(
        `${API}/admin/vip-capital-deposits/${id}/confirm`,
        force ? { force: true } : {},
        { withCredentials: true },
      );
      toast.success(t("adminVipLedgerOps.confirmedToast"));
      setDupConfirm(null);
      load();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (detail?.code === "DUPLICATE_TX_HASH") {
        setDupConfirm({ id, detail });
        return;
      }
      toast.error(typeof detail === "string" ? detail : t("adminVipLedgerOps.actionError"));
    }
  };

  return (
    <div className="space-y-3" data-testid="admin-capital-deposits">
      <FilterBar current={statusFilter} onChange={setStatusFilter}
                 options={["pending", "confirmed", "rejected"]}
                 tPrefix="adminVipLedgerOps.filter." />

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colVip")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("adminVipLedgerOps.colAmount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colMethod")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colProof")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colNote")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("adminVipLedgerOps.colCreated")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colStatus")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan="8" className="text-center text-neutral-500 py-8">{t("admin.common.loadingEllipsis")}</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan="8" className="text-center text-neutral-500 py-8" data-testid="capital-deposits-empty">
                {t("adminVipLedgerOps.empty")}
              </td></tr>
            )}
            {!loading && items.map((it) => (
              <tr key={it.id} className="border-b border-white/5" data-testid={`capital-deposit-row-${it.id}`}>
                <td className="px-4 py-3">
                  <div className="text-white text-xs">{it.vip_name || "—"}</div>
                  <div className="text-[0.65rem] text-neutral-500 font-mono">{it.vip_email}</div>
                  <AdminLedgerPdfButton vipUserId={it.vip_user_id} vipEmail={it.vip_email} />
                </td>
                <td className="px-4 py-3 font-mono text-emerald-400 text-right">
                  ${Number(it.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  <span className="text-[0.6rem] text-neutral-500 ml-1">{it.currency}</span>
                </td>
                <td className="px-4 py-3 text-xs" data-testid={`deposit-method-${it.id}`}>
                  <div className="text-neutral-300 uppercase font-mono">
                    {it.deposit_method ? t(`vipLedgerOps.method.${it.deposit_method}`, it.deposit_method) : "—"}
                  </div>
                  {it.account_holder && (
                    <div className="text-[0.65rem] text-neutral-500 mt-0.5">
                      {t("adminVipLedgerOps.holderLabel")}: <span className="text-neutral-300">{it.account_holder}</span>
                    </div>
                  )}
                  {it.tx_hash && (
                    <div className="mt-0.5 max-w-[180px]">
                      <CopyableText
                        value={it.tx_hash}
                        toastMessage={t("adminVipLedgerOps.hashCopied")}
                        testid={`deposit-hash-${it.id}`}
                        className="text-[0.65rem] text-emerald-400"
                      />
                    </div>
                  )}
                  {it.duplicate_hash && (
                    <div
                      className="mt-1 inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border border-amber-500/50 bg-amber-500/10 text-amber-400 font-mono"
                      data-testid={`deposit-dup-warning-${it.id}`}
                    >
                      <AlertTriangle className="w-3 h-3" /> {t("adminVipLedgerOps.dupWarningBadge")}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-xs">
                  {it.proof_url ? (
                    <a
                      href={it.proof_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-testid={`proof-link-${it.id}`}
                      className="inline-flex items-center gap-1 text-[#8B5CF6] hover:underline"
                    >
                      {t("adminVipLedgerOps.viewProof")} <ExternalLink className="w-3 h-3" />
                    </a>
                  ) : <span className="text-neutral-600">—</span>}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-400 max-w-xs line-clamp-2">
                  {it.note || "—"}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">
                  {new Date(it.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={it.status} />
                </td>
                <td className="px-4 py-3">
                  {it.status === "pending" ? (
                    <div className="flex gap-2">
                      <Button
                        onClick={() => confirm(it.id)}
                        data-testid={`capital-deposit-confirm-${it.id}`}
                        className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-8 px-3 text-xs font-semibold"
                      >
                        <Check className="w-3 h-3 mr-1" /> {t("adminVipLedgerOps.confirm")}
                      </Button>
                      <Button
                        onClick={() => setRejecting({ ...it, kind: "deposit" })}
                        data-testid={`capital-deposit-reject-${it.id}`}
                        variant="ghost"
                        className="rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8 px-3 text-xs"
                      >
                        <XIcon className="w-3 h-3 mr-1" /> {t("adminVipLedgerOps.reject")}
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-neutral-500">
                      {it.balance_delta_usdt != null ? `+$${Number(it.balance_delta_usdt).toFixed(2)} USDT` : "—"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RejectDialog
        rejecting={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => { setRejecting(null); load(); }}
      />
      <DuplicateHashDialog
        dup={dupConfirm}
        onClose={() => setDupConfirm(null)}
        onForce={() => confirm(dupConfirm.id, true)}
      />
    </div>
  );
}


/** iter112b — Warning dialog when the deposit's tx hash was already used. */
function DuplicateHashDialog({ dup, onClose, onForce }) {
  const { t } = useTranslation();
  if (!dup) return null;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        data-testid="dup-hash-dialog"
        className="bg-[#0c0c0c] border border-amber-500/40 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-amber-400">
            <AlertTriangle className="w-5 h-5" />
            {t("adminVipLedgerOps.dupDialogTitle")}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-300 leading-relaxed">
          {t("adminVipLedgerOps.dupDialogBody")}
        </p>
        <div className="border border-white/10 divide-y divide-white/5 max-h-48 overflow-y-auto">
          {(dup.detail?.duplicates || []).map((d) => (
            <div
              key={d.id}
              className="px-3 py-2 text-xs flex items-center justify-between gap-2"
              data-testid={`dup-row-${d.id}`}
            >
              <div className="min-w-0">
                <div className="text-white truncate">{d.vip_email}</div>
                <div className="text-neutral-500">{new Date(d.created_at).toLocaleString()}</div>
              </div>
              <div className="text-right shrink-0">
                <div className="font-mono text-white">
                  ${Number(d.amount).toLocaleString()}
                  <span className="text-[0.6rem] text-neutral-500 ml-1">{d.currency}</span>
                </div>
                <div className="text-[0.6rem] uppercase text-amber-400">
                  {t(`vipLedgerOps.status.${d.status}`, d.status)}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button
            variant="ghost"
            onClick={onClose}
            data-testid="dup-cancel-btn"
            className="rounded-none text-neutral-400 hover:text-white"
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={onForce}
            data-testid="dup-force-confirm-btn"
            className="rounded-none bg-amber-500 hover:bg-amber-400 text-black"
          >
            {t("adminVipLedgerOps.dupConfirmAnyway")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


export function AdminSettlements({ onChanged }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [loading, setLoading] = useState(true);
  const [rejecting, setRejecting] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/vip-settlements`, {
        params: { status: statusFilter, limit: 300 },
        withCredentials: true,
      });
      setItems(r.data?.items || []);
      onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipLedgerOps.loadError"));
    } finally { setLoading(false); }
  }, [statusFilter, t, onChanged]);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("settlement_request", load);

  const approve = async (id) => {
    try {
      await axios.post(`${API}/admin/vip-settlements/${id}/approve`, {}, { withCredentials: true });
      toast.success(t("adminVipLedgerOps.approvedToast"));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipLedgerOps.actionError"));
    }
  };

  return (
    <div className="space-y-3" data-testid="admin-settlements">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <FilterBar current={statusFilter} onChange={setStatusFilter}
                   options={["pending", "confirmed", "rejected"]}
                   tPrefix="adminVipLedgerOps.filter." />
        <Button
          onClick={() => setCreating(true)}
          data-testid="admin-register-settlement-btn"
          className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-9 px-3 text-xs uppercase tracking-widest font-semibold"
        >
          <Plus className="w-4 h-4 mr-1" /> {t("adminVipLedgerOps.registerBtn")}
        </Button>
      </div>

      <div className="tactile-card overflow-x-auto">
        <table className="w-full text-sm min-w-[1000px]">
          <thead className="border-b border-white/10 bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colVip")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colDirection")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 text-right">{t("adminVipLedgerOps.colAmount")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colMethod")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colOrigin")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500 whitespace-nowrap">{t("adminVipLedgerOps.colCreated")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colStatus")}</th>
              <th className="px-4 py-3 micro-label text-neutral-500">{t("adminVipLedgerOps.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan="8" className="text-center text-neutral-500 py-8">{t("admin.common.loadingEllipsis")}</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan="8" className="text-center text-neutral-500 py-8" data-testid="settlements-empty">
                {t("adminVipLedgerOps.empty")}
              </td></tr>
            )}
            {!loading && items.map((it) => (
              <tr key={it.id} className="border-b border-white/5" data-testid={`settlement-row-${it.id}`}>
                <td className="px-4 py-3">
                  <div className="text-white text-xs">{it.vip_name || "—"}</div>
                  <div className="text-[0.65rem] text-neutral-500 font-mono">{it.vip_email}</div>
                  <AdminLedgerPdfButton vipUserId={it.vip_user_id} vipEmail={it.vip_email} />
                </td>
                <td className="px-4 py-3">
                  <DirectionBadge direction={it.direction} />
                </td>
                <td className="px-4 py-3 font-mono text-white text-right">
                  ${Number(it.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  <span className="text-[0.6rem] text-neutral-500 ml-1">{it.currency}</span>
                  <div className="text-[0.6rem] text-neutral-500">≈ ${Number(it.amount_usdt).toFixed(2)} USDT</div>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-300 uppercase font-mono">
                  {t(`vipLedgerOps.method.${it.settlement_method}`, it.settlement_method)}
                </td>
                <td className="px-4 py-3 text-xs">
                  <span className={`px-2 py-0.5 border font-mono text-[0.6rem] uppercase ${
                    it.requested_by === "admin"
                      ? "border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6]"
                      : "border-amber-500/40 bg-amber-500/10 text-amber-400"
                  }`}>
                    {t(`adminVipLedgerOps.origin.${it.requested_by}`)}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 whitespace-nowrap">
                  {new Date(it.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={it.status} />
                </td>
                <td className="px-4 py-3">
                  {it.status === "pending" ? (
                    <div className="flex gap-2">
                      <Button
                        onClick={() => approve(it.id)}
                        data-testid={`settlement-approve-${it.id}`}
                        className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black h-8 px-3 text-xs font-semibold"
                      >
                        <Check className="w-3 h-3 mr-1" /> {t("adminVipLedgerOps.approve")}
                      </Button>
                      <Button
                        onClick={() => setRejecting({ ...it, kind: "settlement" })}
                        data-testid={`settlement-reject-${it.id}`}
                        variant="ghost"
                        className="rounded-none border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8 px-3 text-xs"
                      >
                        <XIcon className="w-3 h-3 mr-1" /> {t("adminVipLedgerOps.reject")}
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-neutral-500">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RegisterSettlementDialog
        open={creating}
        onClose={() => setCreating(false)}
        onDone={() => { setCreating(false); load(); }}
      />
      <RejectDialog
        rejecting={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => { setRejecting(null); load(); }}
      />
    </div>
  );
}


function FilterBar({ current, onChange, options, tPrefix }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {options.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onChange(s)}
          data-testid={`ledger-filter-${s}`}
          className={`text-xs uppercase tracking-widest px-3 py-1.5 border font-mono transition-colors ${
            current === s
              ? "bg-[#8B5CF6]/10 border-[#8B5CF6] text-[#8B5CF6]"
              : "bg-transparent border-white/10 text-neutral-400 hover:border-white/30"
          }`}
        >
          {t(`${tPrefix}${s}`)}
        </button>
      ))}
    </div>
  );
}


function StatusPill({ status }) {
  const { t } = useTranslation();
  const map = {
    pending:   { cls: "border-amber-500/40 bg-amber-500/5 text-amber-400", Icon: Clock },
    confirmed: { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: Check },
    rejected:  { cls: "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]", Icon: XIcon },
  }[status] || {};
  const Icon = map.Icon || Clock;
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border font-mono ${map.cls || ""}`}>
      <Icon className="w-3 h-3" />
      {t(`vipLedgerOps.status.${status}`, status)}
    </span>
  );
}


function DirectionBadge({ direction }) {
  const { t } = useTranslation();
  const isPayout = direction === "payout";
  const Icon = isPayout ? HandCoins : Coins;
  const cls = isPayout
    ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
    : "border-emerald-500/40 bg-emerald-500/10 text-emerald-400";
  return (
    <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-2 py-1 border font-mono ${cls}`}>
      <Icon className="w-3 h-3" />
      {t(`vipLedgerOps.direction.${direction}`)}
    </span>
  );
}


/** iter111 — Admin per-VIP ledger export controls (PDF download + Email). */
function AdminLedgerPdfButton({ vipUserId, vipEmail }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const download = async (e) => {
    e.stopPropagation();
    setBusy(true);
    try {
      const r = await axios.get(
        `${API}/admin/vip-ledger/${encodeURIComponent(vipUserId)}/export.pdf`,
        { withCredentials: true, responseType: "blob" },
      );
      const slug = (vipEmail || vipUserId).split("@")[0].replace(/\s+/g, "_");
      const url = window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `vip_ledger_${slug}_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast.error(t("vipLedgerOps.pdfError"));
    } finally { setBusy(false); }
  };
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      <button
        type="button"
        onClick={download}
        disabled={busy}
        data-testid={`admin-ledger-pdf-${vipUserId}`}
        title={t("vipLedgerOps.pdfHint")}
        className="inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-2 py-0.5 border border-white/10 text-neutral-400 hover:text-[#8B5CF6] hover:border-[#8B5CF6]/60 font-mono transition-colors disabled:opacity-40"
      >
        <FileDown className="w-3 h-3" />
        {busy ? t("vipLedgerOps.downloadingPdf") : t("vipLedgerOps.downloadPdf")}
      </button>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setEmailOpen(true); }}
        data-testid={`admin-ledger-email-${vipUserId}`}
        title={t("vipLedgerOps.emailHint")}
        className="inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-2 py-0.5 border border-white/10 text-neutral-400 hover:text-[#8B5CF6] hover:border-[#8B5CF6]/60 font-mono transition-colors"
      >
        <Mail className="w-3 h-3" />
        {t("vipLedgerOps.emailPdf")}
      </button>
      <EmailLedgerDialog
        open={emailOpen}
        onClose={() => setEmailOpen(false)}
        mode="admin"
        vipUserId={vipUserId}
        defaultTo={vipEmail || ""}
      />
    </div>
  );
}


function RegisterSettlementDialog({ open, onClose, onDone }) {
  const { t } = useTranslation();
  const [vipUserId, setVipUserId] = useState("");
  const [direction, setDirection] = useState("collection");
  const [currency, setCurrency] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setVipUserId(""); setDirection("collection"); setCurrency("USDT");
      setAmount(""); setMethod("cash"); setNote("");
    }
  }, [open]);

  const submit = async () => {
    setBusy(true);
    try {
      await axios.post(`${API}/admin/vip-settlements`, {
        vip_user_id: vipUserId.trim(),
        direction,
        currency: currency.trim().toUpperCase(),
        amount: Number(amount),
        settlement_method: method,
        note: note.trim() || null,
      }, { withCredentials: true });
      toast.success(t("adminVipLedgerOps.registeredToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipLedgerOps.actionError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="admin-register-settlement-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("adminVipLedgerOps.registerTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-400 leading-relaxed">
          {t("adminVipLedgerOps.registerBody")}
        </p>

        <div className="space-y-3 mt-2">
          <div>
            <Label className="micro-label text-neutral-500">VIP user_id</Label>
            <Input
              data-testid="register-vip-id"
              value={vipUserId}
              onChange={(e) => setVipUserId(e.target.value)}
              placeholder="user_test_vip01"
              className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1 font-mono"
            />
          </div>

          <div>
            <Label className="micro-label text-neutral-500">
              {t("vipLedgerOps.directionLabel")}
            </Label>
            <Select value={direction} onValueChange={setDirection}>
              <SelectTrigger data-testid="register-direction" className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#0c0c0c] border border-white/10 rounded-none">
                <SelectItem value="collection" className="rounded-none">
                  {t("vipLedgerOps.direction.collection")} — {t("adminVipLedgerOps.collectionHelp")}
                </SelectItem>
                <SelectItem value="payout" className="rounded-none">
                  {t("vipLedgerOps.direction.payout")} — {t("adminVipLedgerOps.payoutHelp")}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="micro-label text-neutral-500">{t("vipLedgerOps.currencyLabel")}</Label>
              <Input
                data-testid="register-currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                maxLength={16}
                className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1 font-mono uppercase"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("vipLedgerOps.amountLabel")}</Label>
              <Input
                data-testid="register-amount"
                type="number"
                min="0.01"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1 font-mono"
              />
            </div>
          </div>

          <div>
            <Label className="micro-label text-neutral-500">{t("vipLedgerOps.methodLabel")}</Label>
            <Select value={method} onValueChange={setMethod}>
              <SelectTrigger data-testid="register-method" className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#0c0c0c] border border-white/10 rounded-none">
                {METHODS.map((m) => (
                  <SelectItem key={m.code} value={m.code} className="rounded-none">
                    {t(m.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="micro-label text-neutral-500">{t("vipLedgerOps.noteLabel")}</Label>
            <Input
              data-testid="register-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={300}
              className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-4">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400 hover:text-white">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy || !vipUserId.trim() || !amount || !currency.trim()}
            data-testid="register-submit"
            className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white disabled:opacity-40"
          >
            {t("adminVipLedgerOps.registerBtn")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function RejectDialog({ rejecting, onClose, onDone }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (rejecting) setNote(""); }, [rejecting]);

  const submit = async () => {
    if (!rejecting) return;
    setBusy(true);
    try {
      const url = rejecting.kind === "deposit"
        ? `${API}/admin/vip-capital-deposits/${rejecting.id}/reject`
        : `${API}/admin/vip-settlements/${rejecting.id}/reject`;
      await axios.post(url, { admin_note: note.trim() }, { withCredentials: true });
      toast.success(t("adminVipLedgerOps.rejectedToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminVipLedgerOps.actionError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={!!rejecting} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="ledger-reject-dialog"
        className="bg-[#0c0c0c] border border-[#EF4444]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("adminVipLedgerOps.rejectDialogTitle")}</DialogTitle>
        </DialogHeader>
        <textarea
          data-testid="ledger-reject-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={300}
          placeholder={t("adminVipLedgerOps.rejectPlaceholder")}
          className="w-full mt-2 bg-black/40 border border-white/10 rounded-none px-3 py-2 text-sm text-white placeholder:text-neutral-600 focus:border-[#EF4444]/50 focus:outline-none"
        />
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            data-testid="ledger-reject-confirm"
            className="rounded-none bg-[#EF4444] hover:bg-[#F87171] text-white disabled:opacity-40"
          >
            {t("adminVipLedgerOps.reject")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
