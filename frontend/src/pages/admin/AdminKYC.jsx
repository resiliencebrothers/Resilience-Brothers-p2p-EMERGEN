import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import axios from "axios";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  IdCard, Check, X, Loader2, Clock, CheckCircle2, XCircle, AlertTriangle,
  Info, ShieldAlert, User, Mail, Phone, RefreshCw, Search, Keyboard,
} from "lucide-react";
import { extractDetailMessage } from "@/utils/apiErrors";

const REJECT_REASON_KEYS = [
  "blurry",
  "expired",
  "selfie_mismatch",
  "manipulated",
  "name_mismatch",
  "invalid_country",
  "incomplete",
];

/**
 * AdminKYC — iter55.36q keyboard-driven review console.
 *
 * Route: /admin/kyc (staff-only)
 */
export default function AdminKYC() {
  const { t } = useTranslation();

  const STATUS_TABS = [
    { key: "pending", labelKey: "admin.kycAdmin.tabPending", icon: Clock },
    { key: "needs_more_info", labelKey: "admin.kycAdmin.tabMoreInfo", icon: Info },
    { key: "verified", labelKey: "admin.kycAdmin.tabVerified", icon: CheckCircle2 },
    { key: "rejected", labelKey: "admin.kycAdmin.tabRejected", icon: XCircle },
  ];

  const REJECT_REASONS = REJECT_REASON_KEYS.map((k) => ({
    key: k,
    label: t(`admin.kycAdmin.reject_reasons.${k}`),
  }));

  const KBD_HINT = [
    { keys: ["J", "↓"], label: t("admin.kycAdmin.kbdNext") },
    { keys: ["K", "↑"], label: t("admin.kycAdmin.kbdPrev") },
    { keys: ["A"], label: t("admin.kycAdmin.kbdApprove") },
    { keys: ["R"], label: t("admin.kycAdmin.kbdReject") },
    { keys: ["I"], label: t("admin.kycAdmin.kbdMoreInfo") },
    { keys: ["X"], label: t("admin.kycAdmin.kbdToggle") },
    { keys: ["Shift", "A"], label: t("admin.kycAdmin.kbdBulkApprove") },
    { keys: ["Enter"], label: t("admin.kycAdmin.kbdConfirmDialog") },
    { keys: ["Esc"], label: t("admin.kycAdmin.kbdCloseDialog") },
    { keys: ["?"], label: t("admin.kycAdmin.kbdShowHelp") },
  ];

  const [tab, setTab] = useState("pending");
  const [items, setItems] = useState([]);
  const [funnel, setFunnel] = useState(null);
  const [search, setSearch] = useState("");
  const [minRisk, setMinRisk] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null); // full item in action dialog
  const [action, setAction] = useState(null);      // "approve" | "reject" | "more_info"
  const [notes, setNotes] = useState("");
  const [reasons, setReasons] = useState([]);
  const [saving, setSaving] = useState(false);

  // Keyboard navigation state
  const [focusedIdx, setFocusedIdx] = useState(0);
  const [batchIds, setBatchIds] = useState(new Set());
  const [showHelp, setShowHelp] = useState(false);
  const [bulkRunning, setBulkRunning] = useState(false);
  const listRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [q, f] = await Promise.all([
        axios.get(`${API}/admin/kyc/queue`, {
          params: { status: tab, search: search || undefined, min_risk: minRisk || undefined },
          withCredentials: true,
        }),
        axios.get(`${API}/admin/kyc/funnel`, { withCredentials: true }),
      ]);
      setItems(q.data.items || []);
      setFunnel(f.data);
      setFocusedIdx(0);
      setBatchIds(new Set());
    } catch (e) {
      toast.error(extractDetailMessage(e, t("admin.kycAdmin.loadError")));
    } finally {
      setLoading(false);
    }
  }, [tab, search, minRisk, t]);

  useEffect(() => { load(); }, [load]);

  const openAction = useCallback((v, kind) => {
    setSelected(v);
    setAction(kind);
    setNotes("");
    setReasons([]);
  }, []);

  const submitAction = async () => {
    if (action === "reject" && reasons.length === 0) {
      toast.error(t("admin.kycAdmin.reasonRequired"));
      return;
    }
    if (action === "more_info" && notes.trim().length < 5) {
      toast.error(t("admin.kycAdmin.moreInfoMin"));
      return;
    }
    setSaving(true);
    try {
      const endpoint = action === "more_info" ? "request-more-info" : action;
      const payload = action === "reject"
        ? { reasons, notes: notes.trim() }
        : { notes: notes.trim() };
      await axios.post(`${API}/admin/kyc/${selected.id}/${endpoint}`, payload, { withCredentials: true });
      toast.success(
        action === "approve" ? t("admin.kycAdmin.toastApproved") :
        action === "reject"  ? t("admin.kycAdmin.toastRejected") :
                               t("admin.kycAdmin.toastMoreInfo")
      );
      setSelected(null);
      setAction(null);
      await load();
    } catch (e) {
      toast.error(extractDetailMessage(e, t("admin.kycAdmin.toastError")));
    } finally {
      setSaving(false);
    }
  };

  const bulkApprove = useCallback(async () => {
    const ids = Array.from(batchIds);
    if (ids.length === 0) {
      toast.error(t("admin.kycAdmin.bulkNoSelection"));
      return;
    }
    if (!window.confirm(t("admin.kycAdmin.bulkConfirm", { n: ids.length }))) return;
    setBulkRunning(true);
    try {
      const r = await axios.post(
        `${API}/admin/kyc/bulk-approve`,
        { ids, notes: "" },
        { withCredentials: true },
      );
      const { approved_count, failed_count, failed } = r.data;
      if (approved_count > 0) {
        toast.success(t("admin.kycAdmin.bulkSuccess", { n: approved_count }));
      }
      if (failed_count > 0) {
        toast.error(t("admin.kycAdmin.bulkPartialFail", { n: failed_count }), {
          description: failed.map((f) => f.id.slice(0, 8)).join(", "),
        });
      }
      setBatchIds(new Set());
      await load();
    } catch (e) {
      toast.error(extractDetailMessage(e, t("admin.kycAdmin.bulkError")));
    } finally {
      setBulkRunning(false);
    }
  }, [batchIds, load, t]);

  const toggleBatch = useCallback((id) => {
    setBatchIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleReason = (r) => {
    setReasons((prev) => prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]);
  };

  // Actionable rows only (pending / needs_more_info)
  const actionableItems = useMemo(
    () => items.filter((v) => v.status === "pending" || v.status === "needs_more_info"),
    [items],
  );

  // ---------- Global keyboard handler ----------
  useEffect(() => {
    const isTyping = (el) => {
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
    };

    const handler = (e) => {
      // Never intercept while typing in a real input
      if (isTyping(document.activeElement)) return;
      // Don't hijack keys while an action dialog is open (except Enter/Esc which
      // are handled natively by Dialog)
      if (selected) return;
      if (showHelp) {
        if (e.key === "Escape" || e.key === "?") setShowHelp(false);
        return;
      }

      const focused = items[focusedIdx];
      const key = e.key;

      // Navigation
      if (key === "j" || key === "J" || key === "ArrowDown") {
        e.preventDefault();
        setFocusedIdx((i) => Math.min(items.length - 1, i + 1));
      } else if (key === "k" || key === "K" || key === "ArrowUp") {
        e.preventDefault();
        setFocusedIdx((i) => Math.max(0, i - 1));
      } else if (key === "?") {
        e.preventDefault();
        setShowHelp(true);
      } else if (!focused) {
        return;
      } else if (key === "a" && !e.shiftKey && (focused.status === "pending" || focused.status === "needs_more_info")) {
        e.preventDefault();
        openAction(focused, "approve");
      } else if ((key === "A" && e.shiftKey) || (key === "a" && e.shiftKey)) {
        e.preventDefault();
        bulkApprove();
      } else if (key === "r" || key === "R") {
        if (focused.status === "pending" || focused.status === "needs_more_info") {
          e.preventDefault();
          openAction(focused, "reject");
        }
      } else if (key === "i" || key === "I") {
        if (focused.status === "pending" || focused.status === "needs_more_info") {
          e.preventDefault();
          openAction(focused, "more_info");
        }
      } else if (key === "x" || key === "X") {
        if (focused.status === "pending" || focused.status === "needs_more_info") {
          e.preventDefault();
          toggleBatch(focused.id);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [items, focusedIdx, selected, showHelp, openAction, toggleBatch, bulkApprove]);

  // Scroll focused row into view
  useEffect(() => {
    if (!listRef.current) return;
    const nodes = listRef.current.querySelectorAll("[data-kyc-row]");
    nodes[focusedIdx]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusedIdx]);

  return (
    <div className="space-y-6" data-testid="admin-kyc-page">
      {/* HEADER */}
      <header className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <IdCard className="w-8 h-8 text-[#8B5CF6]" />
            {t("admin.kycAdmin.title")}
          </h1>
          <p className="text-sm text-neutral-500 mt-1">
            <Trans
              i18nKey="admin.kycAdmin.subtitle"
              components={{
                1: <kbd className="kbd" />, 2: <kbd className="kbd" />, 3: <kbd className="kbd" />,
                4: <kbd className="kbd" />, 5: <kbd className="kbd" />, 6: <kbd className="kbd" />,
              }}
            />
          </p>
        </div>
        <Button
          data-testid="kyc-help-btn"
          onClick={() => setShowHelp(true)}
          variant="outline"
          size="sm"
          className="border-white/10 text-neutral-300 hover:bg-white/5"
        >
          <Keyboard className="w-3.5 h-3.5 mr-1.5" /> {t("admin.kycAdmin.shortcuts")}
        </Button>
      </header>

      {/* FUNNEL CARDS */}
      {funnel && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <FunnelCard label={t("admin.kycAdmin.funnelTotal")} value={funnel.total_users} icon={User} tone="neutral" testid="funnel-total" />
          <FunnelCard label={t("admin.kycAdmin.funnelPending")} value={funnel.pending} icon={Clock} tone="warn" testid="funnel-pending" />
          <FunnelCard label={t("admin.kycAdmin.funnelHighRisk")} value={funnel.high_risk_pending} icon={ShieldAlert} tone="danger" testid="funnel-high-risk" />
          <FunnelCard label={t("admin.kycAdmin.funnelMoreInfo")} value={funnel.needs_more_info} icon={Info} tone="neutral" testid="funnel-more-info" />
          <FunnelCard label={t("admin.kycAdmin.funnelVerified")} value={funnel.verified} icon={CheckCircle2} tone="ok" testid="funnel-verified" />
          <FunnelCard label={t("admin.kycAdmin.funnelRejected")} value={funnel.rejected} icon={XCircle} tone="muted" testid="funnel-rejected" />
        </div>
      )}

      {/* CONTROLS */}
      <div className="flex flex-col md:flex-row gap-3 md:items-center">
        <Tabs value={tab} onValueChange={setTab} className="w-full md:w-auto">
          <TabsList className="bg-black/40 border border-white/10">
            {STATUS_TABS.map(({ key, labelKey, icon: Icon }) => (
              <TabsTrigger key={key} value={key} data-testid={`kyc-tab-${key}`} className="data-[state=active]:bg-[#8B5CF6] data-[state=active]:text-white text-xs">
                <Icon className="w-3.5 h-3.5 mr-1.5" /> {t(labelKey)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="relative flex-1 md:max-w-xs ml-auto">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
          <Input
            data-testid="kyc-search-input"
            placeholder={t("admin.kycAdmin.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-black/40 border-white/10 text-white text-sm"
          />
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-neutral-500 whitespace-nowrap">{t("admin.kycAdmin.minRisk")}</label>
          <Input
            type="number"
            min={0}
            max={100}
            value={minRisk}
            onChange={(e) => setMinRisk(parseInt(e.target.value || "0", 10))}
            className="w-16 bg-black/40 border-white/10 text-white text-xs text-center"
            data-testid="kyc-min-risk-input"
          />
        </div>

        <Button
          data-testid="kyc-refresh-btn"
          onClick={load}
          size="sm"
          variant="outline"
          className="border-white/10 text-neutral-300 hover:bg-white/5"
        >
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> {t("admin.common.reload")}
        </Button>
      </div>

      {/* BATCH BAR */}
      {actionableItems.length > 0 && (
        <div
          className="flex items-center gap-3 border border-white/10 bg-black/30 px-4 py-2 text-sm"
          data-testid="kyc-batch-bar"
        >
          <Checkbox
            data-testid="kyc-batch-select-all"
            checked={
              batchIds.size > 0 && batchIds.size === actionableItems.length
                ? true
                : batchIds.size > 0 ? "indeterminate" : false
            }
            onCheckedChange={(checked) => {
              if (checked) setBatchIds(new Set(actionableItems.map((v) => v.id)));
              else setBatchIds(new Set());
            }}
          />
          <span className="text-neutral-400">
            {batchIds.size > 0
              ? <Trans i18nKey="admin.kycAdmin.batchSelected" values={{ count: batchIds.size }} components={{ 1: <span className="text-white font-mono" /> }} />
              : t("admin.kycAdmin.batchSelectHint")}
          </span>
          <div className="ml-auto flex items-center gap-2">
            {batchIds.size > 0 && (
              <Button
                data-testid="kyc-clear-batch-btn"
                variant="outline"
                size="sm"
                onClick={() => setBatchIds(new Set())}
                className="border-white/10 text-neutral-400 hover:bg-white/5 h-8"
              >
                {t("admin.kycAdmin.batchClear")}
              </Button>
            )}
            <Button
              data-testid="kyc-bulk-approve-btn"
              size="sm"
              onClick={bulkApprove}
              disabled={batchIds.size === 0 || bulkRunning}
              className="bg-emerald-500 text-black hover:bg-emerald-500/90 h-8 disabled:opacity-40"
            >
              {bulkRunning ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Check className="w-3.5 h-3.5 mr-1.5" />}
              {t("admin.kycAdmin.batchApprove", { label: batchIds.size > 0 ? t("admin.kycAdmin.batchApproveMany", { count: batchIds.size }) : t("admin.kycAdmin.batchApproveOne") })}
            </Button>
          </div>
        </div>
      )}

      {/* LIST */}
      {loading && <div className="text-neutral-500 text-sm">{t("admin.common.loading")}</div>}
      {!loading && items.length === 0 && (
        <div className="text-center py-12 text-neutral-500 border border-white/5 bg-black/30">
          {t("admin.kycAdmin.empty", { context: tab === "pending" ? t("admin.kycAdmin.emptyContextPending") : t("admin.kycAdmin.emptyContextOther", { status: tab }) })}
        </div>
      )}
      {!loading && items.length > 0 && (
        <div className="space-y-2" data-testid="kyc-list" ref={listRef}>
          {items.map((v, idx) => (
            <VerificationRow
              key={v.id}
              v={v}
              idx={idx}
              focused={idx === focusedIdx}
              inBatch={batchIds.has(v.id)}
              onSelect={() => setFocusedIdx(idx)}
              onToggleBatch={() => toggleBatch(v.id)}
              onAction={openAction}
              t={t}
            />
          ))}
        </div>
      )}

      {/* ACTION DIALOG */}
      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="bg-neutral-950 border-white/10 max-w-4xl max-h-[90vh] overflow-y-auto" data-testid="kyc-action-dialog">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="text-white flex items-center gap-2">
                  {action === "approve" && <><CheckCircle2 className="w-5 h-5 text-emerald-400" /> {t("admin.kycAdmin.actionApprove")}</>}
                  {action === "reject" && <><XCircle className="w-5 h-5 text-[#EF4444]" /> {t("admin.kycAdmin.actionReject")}</>}
                  {action === "more_info" && <><Info className="w-5 h-5 text-[#8B5CF6]" /> {t("admin.kycAdmin.actionMoreInfo")}</>}
                </DialogTitle>
                <DialogDescription className="text-neutral-500">
                  {t("admin.kycAdmin.actionDesc")}
                </DialogDescription>
              </DialogHeader>

              <div className="grid md:grid-cols-2 gap-4">
                <div
                  className="border border-white/10 bg-black/40 p-4 space-y-2.5"
                  data-testid="kyc-declared-panel"
                >
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500 mb-2">
                    {t("admin.kycAdmin.declaredPanel")}
                  </div>
                  <ProfileField label={t("admin.kycAdmin.fFullName")} value={selected.user_name} icon={User} />
                  <ProfileField label={t("admin.kycAdmin.fEmail")} value={selected.user_email} icon={Mail} />
                  <ProfileField label={t("admin.kycAdmin.fPhone")} value={selected.user_phone || "—"} icon={Phone} />
                  <ProfileField
                    label={t("admin.kycAdmin.fRiskAuto")}
                    value={`${selected.risk_score}/100`}
                    tone={selected.risk_score >= 60 ? "danger" : selected.risk_score >= 30 ? "warn" : "ok"}
                  />
                  <ProfileField
                    label={t("admin.kycAdmin.fSubmittedAt")}
                    value={selected.created_at?.slice(0, 16).replace("T", " ")}
                  />
                  {selected.submit_ip && (
                    <ProfileField label={t("admin.kycAdmin.fSubmitIp")} value={selected.submit_ip} mono />
                  )}
                  {selected.risk_flags?.length > 0 && (
                    <div className="border border-amber-500/30 bg-amber-500/5 p-2 mt-3 space-y-1">
                      <div className="text-[0.65rem] font-semibold text-amber-300 flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5" /> {t("admin.kycAdmin.riskSignals")}
                      </div>
                      {selected.risk_flags.map((f) => (
                        <div key={f.code} className="text-[0.7rem] text-amber-200">
                          • [{f.severity}] {f.message}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div
                  className="border border-white/10 bg-black/40 p-4 space-y-2"
                  data-testid="kyc-documents-panel"
                >
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500 mb-1">
                    {t("admin.kycAdmin.documentsPanel", { n: selected.documents?.length || 0 })}
                  </div>
                  {selected.documents?.map((d) => (
                    <div key={d.doc_type} className="space-y-1">
                      <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">
                        {d.doc_type.replace("_", " ")}
                      </div>
                      <a href={d.ref} target="_blank" rel="noreferrer" className="block">
                        <img
                          src={d.ref}
                          alt={d.doc_type}
                          className="w-full h-40 object-contain bg-neutral-900 border border-white/10 hover:border-[#8B5CF6]/60 transition"
                          data-testid={`kyc-doc-${d.doc_type}`}
                        />
                      </a>
                    </div>
                  ))}
                </div>
              </div>

              {action === "reject" && (
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wider text-neutral-500">{t("admin.kycAdmin.reasonsLabel")}</label>
                  {REJECT_REASONS.map((r) => (
                    <label key={r.key} className="flex items-center gap-2 text-sm text-neutral-200 cursor-pointer">
                      <Checkbox
                        data-testid={`kyc-reject-reason-${r.key}`}
                        checked={reasons.includes(r.label)}
                        onCheckedChange={() => toggleReason(r.label)}
                      />
                      {r.label}
                    </label>
                  ))}
                </div>
              )}

              <div>
                <label className="text-xs uppercase tracking-wider text-neutral-500">
                  {action === "more_info" ? t("admin.kycAdmin.notesMoreInfo") : t("admin.kycAdmin.notesInternal")}
                </label>
                <Textarea
                  data-testid="kyc-action-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  placeholder={
                    action === "more_info"
                      ? t("admin.kycAdmin.notesMoreInfoPh")
                      : ""
                  }
                  className="bg-black/40 border-white/10 text-white text-sm mt-1"
                />
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setSelected(null)} className="border-white/10 text-neutral-300 hover:bg-white/5">
                  {t("admin.common.cancel")}
                </Button>
                <Button
                  data-testid="kyc-action-submit"
                  onClick={submitAction}
                  disabled={saving}
                  className={
                    action === "approve" ? "bg-emerald-500 text-black hover:bg-emerald-500/90" :
                    action === "reject" ? "bg-[#EF4444] text-white hover:bg-[#EF4444]/90" :
                    "bg-[#8B5CF6] text-white hover:bg-[#8B5CF6]/90"
                  }
                >
                  {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                  {t("admin.kycAdmin.confirm")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* KEYBOARD HELP DIALOG */}
      <Dialog open={showHelp} onOpenChange={setShowHelp}>
        <DialogContent
          className="bg-neutral-950 border-white/10 max-w-md"
          data-testid="kyc-help-dialog"
        >
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Keyboard className="w-5 h-5 text-[#8B5CF6]" /> {t("admin.kycAdmin.shortcutsTitle")}
            </DialogTitle>
            <DialogDescription className="text-neutral-500">
              {t("admin.kycAdmin.shortcutsDesc")}
            </DialogDescription>
          </DialogHeader>
          <ul className="space-y-2">
            {KBD_HINT.map(({ keys, label }) => (
              <li key={label} className="flex items-center justify-between gap-4 text-sm">
                <span className="text-neutral-300">{label}</span>
                <span className="flex gap-1 items-center">
                  {keys.map((k, i) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-neutral-500 text-xs">+</span>}
                      <kbd className="kbd">{k}</kbd>
                    </span>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>

      {/* Local styles for <kbd> */}
      <style>{`
        .kbd {
          display: inline-block;
          padding: 1px 6px;
          font-family: ui-monospace, SFMono-Regular, monospace;
          font-size: 11px;
          line-height: 1.4;
          color: #e5e7eb;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.15);
          border-bottom-width: 2px;
          border-radius: 3px;
          box-shadow: 0 1px 0 rgba(0,0,0,0.4);
        }
      `}</style>
    </div>
  );
}

function ProfileField({ label, value, icon: Icon, tone, mono }) {
  const toneCls = {
    danger: "text-[#EF4444]",
    warn: "text-amber-300",
    ok: "text-emerald-400",
  }[tone] || "text-white";
  return (
    <div className="flex items-start gap-2">
      {Icon && <Icon className="w-3.5 h-3.5 text-neutral-500 mt-0.5 flex-shrink-0" />}
      <div className="min-w-0 flex-1">
        <div className="text-[0.6rem] uppercase tracking-wider text-neutral-500">{label}</div>
        <div className={`text-sm ${mono ? "font-mono" : ""} ${toneCls} break-words`}>
          {value || <span className="text-neutral-600 italic">—</span>}
        </div>
      </div>
    </div>
  );
}

function FunnelCard({ label, value, icon: Icon, tone, testid }) {
  const toneClasses = {
    neutral: "border-white/10 bg-black/30 text-white",
    warn: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5 text-[#FEF3C7]",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
    ok: "border-emerald-500/40 bg-emerald-500/5 text-emerald-200",
    muted: "border-white/5 bg-black/20 text-neutral-400",
  };
  return (
    <div className={`border ${toneClasses[tone]} p-3`} data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[0.65rem] uppercase tracking-wider opacity-70">{label}</span>
        <Icon className="w-4 h-4 opacity-60" />
      </div>
      <div className="text-2xl font-bold">{value ?? 0}</div>
    </div>
  );
}

function VerificationRow({ v, idx, focused, inBatch, onSelect, onToggleBatch, onAction, t }) {
  const statusStyle = {
    pending: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5",
    needs_more_info: "border-blue-500/40 bg-blue-500/5",
    verified: "border-emerald-500/40 bg-emerald-500/5",
    rejected: "border-neutral-500/30 bg-neutral-500/5",
  }[v.status];
  const riskColor = v.risk_score >= 60 ? "text-[#EF4444]" : v.risk_score >= 30 ? "text-[#8B5CF6]" : "text-emerald-400";
  const isActionable = v.status === "pending" || v.status === "needs_more_info";
  const focusRing = focused ? "ring-2 ring-[#8B5CF6] ring-offset-2 ring-offset-black" : "";

  return (
    <div
      data-kyc-row
      className={`border ${statusStyle} ${focusRing} p-4 cursor-pointer transition-shadow`}
      data-testid={`kyc-row-${v.id}`}
      onClick={onSelect}
    >
      <div className="flex flex-col md:flex-row md:items-start gap-3">
        {isActionable && (
          <Checkbox
            data-testid={`kyc-batch-checkbox-${v.id}`}
            checked={inBatch}
            onCheckedChange={onToggleBatch}
            onClick={(e) => e.stopPropagation()}
            className="mt-1"
          />
        )}
        <div className="flex-1 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-white flex items-center gap-1.5">
              <User className="w-4 h-4 text-neutral-500" /> {v.user_name}
            </div>
            <span className={`text-xs font-mono ${riskColor}`}>{t("admin.kycAdmin.rowRisk", { score: v.risk_score })}</span>
            {v.risk_flags?.length > 0 && (
              <span className="text-[0.65rem] text-amber-300 uppercase">
                <AlertTriangle className="inline w-3 h-3 mr-0.5" /> {t("admin.kycAdmin.rowSignals", { n: v.risk_flags.length })}
              </span>
            )}
            {focused && (
              <span className="ml-auto text-[0.65rem] text-[#8B5CF6] uppercase tracking-wider">
                {t("admin.kycAdmin.rowFocused", { n: idx + 1 })}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-neutral-400">
            <span className="flex items-center gap-1"><Mail className="w-3 h-3" /> {v.user_email}</span>
            <span className="flex items-center gap-1"><Phone className="w-3 h-3" /> {v.user_phone || "—"}</span>
            <span className="text-neutral-500">{t("admin.kycAdmin.rowSent", { ts: v.created_at?.slice(0, 16).replace("T", " ") })}</span>
          </div>
          {v.risk_flags?.length > 0 && (
            <ul className="text-[0.7rem] text-amber-200/80 mt-1 space-y-0.5">
              {v.risk_flags.slice(0, 3).map((f) => (
                <li key={f.code}>• {f.message}</li>
              ))}
            </ul>
          )}
          {v.status === "rejected" && v.rejection_reasons?.length > 0 && (
            <div className="text-[0.7rem] text-neutral-400">
              {t("admin.kycAdmin.rowRejectedReasons", { list: v.rejection_reasons.join(" · ") })}
            </div>
          )}
          {v.review_notes && (
            <div className="text-[0.7rem] text-neutral-400 italic">
              {t("admin.kycAdmin.rowNote", { text: v.review_notes })}
            </div>
          )}
        </div>

        {isActionable && (
          <div className="flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
            <Button
              data-testid={`kyc-approve-btn-${v.id}`}
              size="sm"
              onClick={() => onAction(v, "approve")}
              className="bg-emerald-500 text-black hover:bg-emerald-500/90 h-8"
            >
              <Check className="w-3.5 h-3.5 mr-1" /> {t("admin.kycAdmin.rowApprove")}
            </Button>
            <Button
              data-testid={`kyc-more-info-btn-${v.id}`}
              size="sm"
              variant="outline"
              onClick={() => onAction(v, "more_info")}
              className="border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 h-8"
            >
              <Info className="w-3.5 h-3.5 mr-1" /> {t("admin.kycAdmin.rowMoreInfo")}
            </Button>
            <Button
              data-testid={`kyc-reject-btn-${v.id}`}
              size="sm"
              variant="outline"
              onClick={() => onAction(v, "reject")}
              className="border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8"
            >
              <X className="w-3.5 h-3.5 mr-1" /> {t("admin.kycAdmin.rowReject")}
            </Button>
          </div>
        )}
        {v.status === "verified" && (
          <div className="text-emerald-400 text-xs font-semibold flex items-center gap-1">
            <CheckCircle2 className="w-4 h-4" /> {t("admin.kycAdmin.rowVerified")}
          </div>
        )}
        {v.status === "rejected" && (
          <div className="text-[#EF4444] text-xs font-semibold flex items-center gap-1">
            <XCircle className="w-4 h-4" /> {t("admin.kycAdmin.rowRejected")}
          </div>
        )}
      </div>
    </div>
  );
}
