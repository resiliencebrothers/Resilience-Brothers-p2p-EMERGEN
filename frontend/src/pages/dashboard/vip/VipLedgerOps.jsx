import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Clock, Check, X, FileDown, Mail } from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";

/**
 * iter110 · Phases 2+3 → iter113: "Enviar capital" and "Cobrar saldo" were
 * RETIRED (owner decision, 30 Jul 2026) — deposits now live in "Depósitos y
 * Retiros" and batch credits land directly on the per-currency balance.
 * This module keeps the ledger movements HISTORY + the email statement
 * dialog only.
 */


/**
 * iter111.2 · Email VIP ledger PDF statement dialog.
 *
 * Endpoint is picked by `mode`:
 *   - "self"  → POST /api/vip/ledger/email     (VIP sends own statement)
 *   - "admin" → POST /api/admin/vip-ledger/{vipUserId}/email
 */
export function EmailLedgerDialog({
  open, onClose, mode = "self", vipUserId, defaultTo = "",
}) {
  const { t } = useTranslation();
  const [to, setTo] = useState(defaultTo);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) { setTo(defaultTo); setNote(""); } },
    [open, defaultTo]);

  const submit = async () => {
    setBusy(true);
    try {
      const url = mode === "admin"
        ? `${API}/admin/vip-ledger/${encodeURIComponent(vipUserId)}/email`
        : `${API}/vip/ledger/email`;
      const r = await axios.post(url, { to: to.trim(), note: note.trim() },
                                  { withCredentials: true });
      toast.success(t("vipLedgerOps.emailSent", { to: r.data?.to || to }));
      onClose();
    } catch (e) {
      const detail = e.response?.data?.detail || t("vipLedgerOps.emailError");
      toast.error(detail);
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent
        data-testid="email-ledger-dialog"
        className="rounded-none bg-[#0a0a0a] border border-white/10 max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="text-white text-lg font-bold uppercase tracking-widest">
            <Mail className="w-4 h-4 inline mr-2 text-[#8B5CF6]" />
            {t("vipLedgerOps.emailTitle")}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-500">{t("vipLedgerOps.emailHint")}</p>
        <div className="space-y-3 mt-2">
          <div>
            <Label className="micro-label text-neutral-500">
              {t("vipLedgerOps.emailToLabel")}
            </Label>
            <Input
              data-testid="email-ledger-to"
              type="email"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="destinatario@dominio.com"
              className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">
              {t("vipLedgerOps.emailNoteLabel")}
            </Label>
            <Input
              data-testid="email-ledger-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("vipLedgerOps.emailNotePlaceholder")}
              maxLength={600}
              className="rounded-none bg-black/40 border-white/10 text-white h-10 mt-1"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-4">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={busy}
            className="rounded-none text-neutral-400 hover:text-white"
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy || !to.trim()}
            data-testid="email-ledger-submit"
            className="rounded-none bg-[#8B5CF6] hover:bg-[#7C3AED] text-black disabled:opacity-40"
          >
            {busy ? t("vipLedgerOps.emailSending") : t("vipLedgerOps.emailSend")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


/**
 * Unified movements history — mixes capital deposits + settlements sorted
 * by created_at desc.
 */
export function MovementsHistory() {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [dep, set] = await Promise.all([
        axios.get(`${API}/vip/capital-deposits`, { withCredentials: true }),
        axios.get(`${API}/vip/settlements`, { withCredentials: true }),
      ]);
      const merged = [
        ...(dep.data?.items || []).map((d) => ({ ...d, _kind: "deposit" })),
        ...(set.data?.items || []).map((s) => ({ ...s, _kind: "settlement" })),
      ].sort((a, b) => b.created_at.localeCompare(a.created_at));
      setRows(merged);
    } catch {
      setRows([]);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("capital_deposit_decision", load);
  useLiveEvent("settlement_decision", load);

  const [downloading, setDownloading] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const downloadPdf = async () => {
    setDownloading(true);
    try {
      const r = await axios.get(`${API}/vip/ledger/export.pdf`, {
        withCredentials: true,
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `vip_ledger_${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast.error(t("vipLedgerOps.pdfError"));
    } finally { setDownloading(false); }
  };

  return (
    <section className="space-y-3" data-testid="ledger-movements">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="micro-label text-neutral-500">{t("vipLedgerOps.movementsTitle")}</div>
        <div className="flex items-center gap-2">
          <Button
            onClick={() => setEmailOpen(true)}
            data-testid="ledger-email-pdf-btn"
            title={t("vipLedgerOps.emailHint")}
            variant="ghost"
            className="rounded-none border border-white/10 hover:border-[#8B5CF6]/60 hover:text-[#8B5CF6] text-neutral-300 h-8 px-3 text-[0.65rem] uppercase tracking-widest font-mono"
          >
            <Mail className="w-3.5 h-3.5 mr-1.5" />
            {t("vipLedgerOps.emailPdf")}
          </Button>
          <Button
            onClick={downloadPdf}
            disabled={downloading}
            data-testid="ledger-download-pdf-btn"
            title={t("vipLedgerOps.pdfHint")}
            variant="ghost"
            className="rounded-none border border-white/10 hover:border-[#8B5CF6]/60 hover:text-[#8B5CF6] text-neutral-300 h-8 px-3 text-[0.65rem] uppercase tracking-widest font-mono"
          >
            <FileDown className="w-3.5 h-3.5 mr-1.5" />
            {downloading ? t("vipLedgerOps.downloadingPdf") : t("vipLedgerOps.downloadPdf")}
          </Button>
        </div>
      </div>
      <EmailLedgerDialog
        open={emailOpen}
        onClose={() => setEmailOpen(false)}
        mode="self"
      />
      {loading && (
        <div className="text-sm text-neutral-500 py-4 text-center">{t("admin.common.loadingEllipsis")}</div>
      )}
      {!loading && rows.length === 0 && (
        <div className="text-sm text-neutral-500 py-6 text-center border border-white/5 bg-black/20" data-testid="ledger-movements-empty">
          {t("vipLedgerOps.movementsEmpty")}
        </div>
      )}
      {!loading && rows.length > 0 && (
        <div className="tactile-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0a0a] border-b border-white/10">
              <tr className="text-left">
                <th className="px-3 py-2 micro-label text-neutral-500 whitespace-nowrap">{t("vipLedgerOps.colDate")}</th>
                <th className="px-3 py-2 micro-label text-neutral-500 whitespace-nowrap">{t("vipLedgerOps.colKind")}</th>
                <th className="px-3 py-2 micro-label text-neutral-500 text-right whitespace-nowrap">{t("vipLedgerOps.colAmount")}</th>
                <th className="px-3 py-2 micro-label text-neutral-500 whitespace-nowrap">{t("vipLedgerOps.colStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => <MovementRow key={r.id} row={r} />)}
            </tbody>
          </table>
        </div>
      )}
      <MonthlyMailingToggle />
    </section>
  );
}


/**
 * iter111.3 · VIP self-service toggle for the monthly ledger PDF email.
 * Small row shown below the movements history. Persists to
 * `PUT /api/vip/ledger/monthly-preference`.
 */
function MonthlyMailingToggle() {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let ignore = false;
    axios.get(`${API}/vip/ledger/monthly-preference`, { withCredentials: true })
      .then((r) => { if (!ignore) setEnabled(!!r.data?.enabled); })
      .catch(() => { if (!ignore) setEnabled(true); });
    return () => { ignore = true; };
  }, []);

  const toggle = async () => {
    if (enabled === null || busy) return;
    setBusy(true);
    const next = !enabled;
    try {
      await axios.put(`${API}/vip/ledger/monthly-preference`,
                        { enabled: next }, { withCredentials: true });
      setEnabled(next);
      toast.success(next
        ? t("vipLedgerOps.monthlyEnabledToast")
        : t("vipLedgerOps.monthlyDisabledToast"));
    } catch {
      toast.error(t("vipLedgerOps.monthlyToggleError"));
    } finally { setBusy(false); }
  };

  if (enabled === null) return null;
  return (
    <div
      data-testid="monthly-mailing-toggle"
      className="flex items-start justify-between gap-3 border border-white/5 bg-[#0a0a0a]/60 px-3 py-3 text-xs"
    >
      <div className="flex-1 min-w-0">
        <div className="text-neutral-300 font-mono text-[0.65rem] uppercase tracking-widest">
          {t("vipLedgerOps.monthlyToggleTitle")}
        </div>
        <div className="text-neutral-500 mt-0.5 leading-relaxed">
          {t("vipLedgerOps.monthlyToggleHint")}
        </div>
      </div>
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        data-testid="monthly-mailing-btn"
        aria-pressed={enabled}
        className={`shrink-0 inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-3 py-1 border font-mono transition-colors ${
          enabled
            ? "border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
            : "border-white/10 text-neutral-400 hover:text-white hover:border-white/30"
        } disabled:opacity-40`}
      >
        {enabled ? t("vipLedgerOps.monthlyEnabled") : t("vipLedgerOps.monthlyDisabled")}
      </button>
    </div>
  );
}


function MovementRow({ row }) {
  const { t } = useTranslation();
  const isDeposit = row._kind === "deposit";
  const label = isDeposit
    ? t("vipLedgerOps.kind.deposit")
    : row.direction === "payout"
      ? t("vipLedgerOps.kind.payout")
      : t("vipLedgerOps.kind.collection");
  const tone = isDeposit
    ? "text-emerald-400"
    : row.direction === "payout"
      ? "text-amber-400"
      : "text-[#EF4444]";
  const statusMap = {
    pending:   { cls: "border-amber-500/40 bg-amber-500/5 text-amber-400", Icon: Clock },
    confirmed: { cls: "border-emerald-500/40 bg-emerald-500/5 text-emerald-400", Icon: Check },
    rejected:  { cls: "border-[#EF4444]/40 bg-[#EF4444]/10 text-[#EF4444]", Icon: X },
  }[row.status] || {};
  const Icon = statusMap.Icon || Clock;

  return (
    <tr className="border-b border-white/5" data-testid={`movement-row-${row.id}`}>
      <td className="px-3 py-2 text-xs text-neutral-500 font-mono whitespace-nowrap">
        {new Date(row.created_at).toLocaleDateString()}
      </td>
      <td className={`px-3 py-2 text-xs font-mono whitespace-nowrap ${tone}`}>
        {label}
      </td>
      <td className="px-3 py-2 font-mono text-white text-right whitespace-nowrap">
        ${Number(row.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}
        <span className="text-[0.6rem] text-neutral-500 ml-1">{row.currency}</span>
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        <span className={`inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-widest px-1.5 py-0.5 border font-mono ${statusMap.cls || ""}`}>
          <Icon className="w-3 h-3" />
          {t(`vipLedgerOps.status.${row.status}`, row.status)}
        </span>
      </td>
    </tr>
  );
}
