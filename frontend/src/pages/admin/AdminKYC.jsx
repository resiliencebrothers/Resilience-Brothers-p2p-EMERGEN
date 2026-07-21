import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import axios from "axios";
import { useTranslation, Trans } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { IdCard, Keyboard } from "lucide-react";
import { extractDetailMessage } from "@/utils/apiErrors";

import KYCFunnelCards from "./kyc/KYCFunnelCards";
import KYCFilters from "./kyc/KYCFilters";
import KYCBatchBar from "./kyc/KYCBatchBar";
import KYCVerificationRow from "./kyc/KYCVerificationRow";
import KYCActionDialog from "./kyc/KYCActionDialog";
import KYCHelpDialog from "./kyc/KYCHelpDialog";

/**
 * AdminKYC — iter55.36q keyboard-driven review console.
 *
 * Route: /admin/kyc (staff-only)
 *
 * This file is the thin container that owns state, network calls and the
 * keyboard shortcut handler. All UI blocks live in ./kyc/ so each piece
 * stays small, focused and testable in isolation.
 */
export default function AdminKYC() {
  const { t } = useTranslation();

  const [tab, setTab] = useState("pending");
  const [items, setItems] = useState([]);
  const [funnel, setFunnel] = useState(null);
  const [search, setSearch] = useState("");
  const [minRisk, setMinRisk] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [action, setAction] = useState(null);
  const [notes, setNotes] = useState("");
  const [reasons, setReasons] = useState([]);
  const [saving, setSaving] = useState(false);
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

  const closeAction = useCallback(() => {
    setSelected(null);
    setAction(null);
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
      closeAction();
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

  const toggleReason = useCallback((r) => {
    setReasons((prev) => prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]);
  }, []);

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
      if (isTyping(document.activeElement)) return;
      if (selected) return;
      if (showHelp) {
        if (e.key === "Escape" || e.key === "?") setShowHelp(false);
        return;
      }

      const focused = items[focusedIdx];
      const key = e.key;

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

      <KYCFunnelCards funnel={funnel} />

      <KYCFilters
        tab={tab}
        onTabChange={setTab}
        search={search}
        onSearchChange={setSearch}
        minRisk={minRisk}
        onMinRiskChange={setMinRisk}
        onRefresh={load}
      />

      <KYCBatchBar
        actionableItems={actionableItems}
        batchIds={batchIds}
        onBatchIdsChange={setBatchIds}
        bulkRunning={bulkRunning}
        onBulkApprove={bulkApprove}
      />

      {loading && <div className="text-neutral-500 text-sm">{t("admin.common.loading")}</div>}
      {!loading && items.length === 0 && (
        <div className="text-center py-12 text-neutral-500 border border-white/5 bg-black/30">
          {t("admin.kycAdmin.empty", {
            context: tab === "pending"
              ? t("admin.kycAdmin.emptyContextPending")
              : t("admin.kycAdmin.emptyContextOther", { status: tab }),
          })}
        </div>
      )}
      {!loading && items.length > 0 && (
        <div className="space-y-2" data-testid="kyc-list" ref={listRef}>
          {items.map((v, idx) => (
            <KYCVerificationRow
              key={v.id}
              v={v}
              idx={idx}
              focused={idx === focusedIdx}
              inBatch={batchIds.has(v.id)}
              onSelect={() => setFocusedIdx(idx)}
              onToggleBatch={() => toggleBatch(v.id)}
              onAction={openAction}
            />
          ))}
        </div>
      )}

      <KYCActionDialog
        selected={selected}
        action={action}
        notes={notes}
        onNotesChange={setNotes}
        reasons={reasons}
        onToggleReason={toggleReason}
        saving={saving}
        onClose={closeAction}
        onSubmit={submitAction}
      />

      <KYCHelpDialog open={showHelp} onOpenChange={setShowHelp} />

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
