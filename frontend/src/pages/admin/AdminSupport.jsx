import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Send, X, RefreshCw, Ticket as TicketIcon, HelpCircle, Plus, Edit3, Trash2 } from "lucide-react";
import { API } from "@/App";
import AdminPageHeader from "@/components/AdminPageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLiveEvent } from "@/hooks/useLiveStream";

const CATEGORIES = ["general", "kyc", "convert", "withdrawal", "fees", "other"];
const STATUSES = ["open", "answered", "closed"];

const STATUS_BADGE = {
  open:     "bg-[#EAB308]/10 text-[#EAB308] border-[#EAB308]/40",
  answered: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/40",
  closed:   "bg-neutral-500/10 text-neutral-500 border-neutral-500/30",
};

/**
 * iter102 — /admin/support console.
 *
 * Two sub-tabs:
 *   1. Tickets — cola pendiente + hilos con reply/close
 *   2. FAQ    — CRUD sobre `faq_entries`
 */
export default function AdminSupport() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("tickets");
  const [tickets, setTickets] = useState([]);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [loadingTickets, setLoadingTickets] = useState(false);

  const [faq, setFaq] = useState([]);
  const [editing, setEditing] = useState(null);

  const [selectedTicketId, setSelectedTicketId] = useState(null);
  const [reply, setReply] = useState("");
  const [replying, setReplying] = useState(false);

  const loadTickets = useCallback(async () => {
    setLoadingTickets(true);
    try {
      const params = {};
      if (statusFilter) params.status = statusFilter;
      if (categoryFilter) params.category = categoryFilter;
      const r = await axios.get(`${API}/admin/support/tickets`, { params, withCredentials: true });
      setTickets(r.data.items || []);
      setTotal(r.data.total || 0);
      setUnread(r.data.unread || 0);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("adminSupport.loadError"));
    } finally {
      setLoadingTickets(false);
    }
  }, [statusFilter, categoryFilter, t]);

  const loadFaq = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/support/faq`, { withCredentials: true });
      setFaq(r.data || []);
    } catch (e) {
      toast.error(t("adminSupport.faqLoadError"));
    }
  }, [t]);

  useEffect(() => { if (tab === "tickets") loadTickets(); }, [tab, loadTickets]);
  useEffect(() => { if (tab === "faq") loadFaq(); }, [tab, loadFaq]);

  // SSE — refresh whenever a client posts or replies.
  useLiveEvent("support_ticket_created", () => tab === "tickets" && loadTickets());
  useLiveEvent("support_ticket_updated", () => tab === "tickets" && loadTickets());

  const selectedTicket = useMemo(
    () => tickets.find((x) => x.id === selectedTicketId) || null,
    [tickets, selectedTicketId],
  );

  const openTicket = useCallback(async (ticket) => {
    setSelectedTicketId(ticket.id);
    if (ticket.unread_by_staff) {
      try {
        await axios.post(`${API}/admin/support/tickets/${ticket.id}/mark-read`,
                         {}, { withCredentials: true });
        setTickets((prev) => prev.map((x) => x.id === ticket.id ? { ...x, unread_by_staff: false } : x));
        setUnread((u) => Math.max(0, u - 1));
      } catch { /* silent */ }
    }
  }, []);

  const submitReply = useCallback(async () => {
    if (!reply.trim() || !selectedTicket) return;
    setReplying(true);
    try {
      const r = await axios.post(
        `${API}/admin/support/tickets/${selectedTicket.id}/reply`,
        { text: reply.trim(), images: [] },
        { withCredentials: true },
      );
      setTickets((prev) => prev.map((x) => x.id === r.data.id ? r.data : x));
      setReply("");
      toast.success(t("adminSupport.replySent"));
    } catch (e) {
      toast.error(e.response?.data?.detail || t("adminSupport.replyFailed"));
    } finally {
      setReplying(false);
    }
  }, [reply, selectedTicket, t]);

  const closeTicket = useCallback(async () => {
    if (!selectedTicket) return;
    if (!window.confirm(t("adminSupport.confirmClose"))) return;
    try {
      const r = await axios.post(`${API}/admin/support/tickets/${selectedTicket.id}/close`,
                                 {}, { withCredentials: true });
      setTickets((prev) => prev.map((x) => x.id === r.data.id ? r.data : x));
      toast.success(t("adminSupport.closed"));
    } catch (e) {
      toast.error(e.response?.data?.detail || t("adminSupport.closeFailed"));
    }
  }, [selectedTicket, t]);

  const startEditFaq = (entry) => setEditing({ ...entry });
  const startNewFaq = () => setEditing({
    id: null, category: "general", order: 0, is_active: true,
    question_es: "", question_en: "", answer_es: "", answer_en: "",
  });

  const saveFaq = async () => {
    if (!editing) return;
    try {
      const payload = {
        category: editing.category,
        question_es: editing.question_es.trim(),
        question_en: editing.question_en.trim(),
        answer_es: editing.answer_es.trim(),
        answer_en: editing.answer_en.trim(),
        order: Number(editing.order || 0),
        is_active: !!editing.is_active,
      };
      if (editing.id) {
        await axios.put(`${API}/admin/support/faq/${editing.id}`, payload, { withCredentials: true });
      } else {
        await axios.post(`${API}/admin/support/faq`, payload, { withCredentials: true });
      }
      toast.success(t("adminSupport.faqSaved"));
      setEditing(null);
      loadFaq();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("adminSupport.faqSaveFailed"));
    }
  };

  const deleteFaq = async (id) => {
    if (!window.confirm(t("adminSupport.faqConfirmDelete"))) return;
    try {
      await axios.delete(`${API}/admin/support/faq/${id}`, { withCredentials: true });
      toast.success(t("adminSupport.faqDeleted"));
      loadFaq();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("adminSupport.faqDeleteFailed"));
    }
  };

  return (
    <div data-testid="admin-support" className="space-y-6">
      <AdminPageHeader
        eyebrow={t("adminSupport.eyebrow")}
        title={t("adminSupport.title")}
        subtitle={t("adminSupport.subtitle")}
        testid="admin-support-header"
      />

      <div className="flex gap-1 border-b border-white/10">
        <TabBtn id="tickets" active={tab} setTab={setTab} icon={TicketIcon}
                label={t("adminSupport.tabs.tickets")} badge={unread || null} />
        <TabBtn id="faq" active={tab} setTab={setTab} icon={HelpCircle}
                label={t("adminSupport.tabs.faq")} />
      </div>

      {tab === "tickets" && (
        <div className="grid lg:grid-cols-[1fr_1.5fr] gap-4">
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 items-end">
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.filters.status")}</div>
                <Select value={statusFilter || "all"} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
                  <SelectTrigger data-testid="status-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-36">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                    <SelectItem value="all">{t("adminSupport.filters.allStatuses")}</SelectItem>
                    {STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>{t(`support.status.${s}`)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.filters.category")}</div>
                <Select value={categoryFilter || "all"} onValueChange={(v) => setCategoryFilter(v === "all" ? "" : v)}>
                  <SelectTrigger data-testid="category-filter" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                    <SelectItem value="all">{t("adminSupport.filters.allCategories")}</SelectItem>
                    {CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>{t(`support.category.${c}`)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <button
                type="button"
                onClick={loadTickets}
                data-testid="tickets-refresh"
                className="flex items-center gap-1.5 text-xs text-neutral-500 hover:text-[#8B5CF6] ml-auto"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loadingTickets ? "animate-spin" : ""}`} />
                {t("adminSupport.refresh")}
              </button>
            </div>
            <div className="text-[0.65rem] text-neutral-600 font-mono">
              {t("adminSupport.tickets.counter", { total, unread })}
            </div>
            <div className="space-y-1.5 max-h-[70vh] overflow-y-auto">
              {tickets.length === 0 && (
                <div className="tactile-card p-6 text-center text-xs text-neutral-500" data-testid="admin-tickets-empty">
                  {t("adminSupport.tickets.empty")}
                </div>
              )}
              {tickets.map((tk) => (
                <button
                  key={tk.id}
                  data-testid={`admin-ticket-row-${tk.id}`}
                  onClick={() => openTicket(tk)}
                  className={`w-full text-left px-3 py-2.5 border transition-colors ${
                    selectedTicketId === tk.id
                      ? "bg-[#8B5CF6]/10 border-[#8B5CF6]/50"
                      : `bg-black/40 border-white/10 hover:border-white/20 ${tk.unread_by_staff ? "ring-1 ring-[#8B5CF6]/40" : ""}`
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 border font-mono ${STATUS_BADGE[tk.status]}`}>
                      {t(`support.status.${tk.status}`)}
                    </span>
                    <span className="text-[0.6rem] text-neutral-500 font-mono">{t(`support.category.${tk.category}`)}</span>
                    {tk.unread_by_staff && (
                      <span className="ml-auto text-[0.55rem] uppercase tracking-wider bg-[#8B5CF6] text-white px-1 py-0.5">
                        {t("adminSupport.tickets.new")}
                      </span>
                    )}
                  </div>
                  <div className="text-sm truncate">{tk.subject}</div>
                  <div className="text-[0.65rem] text-neutral-600 mt-0.5">
                    {tk.user_name || tk.user_email} · {new Date(tk.updated_at).toLocaleString()}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="tactile-card p-4 min-h-[60vh]">
            {!selectedTicket && (
              <div className="text-center text-neutral-500 py-16" data-testid="admin-ticket-empty-state">
                <TicketIcon className="w-8 h-8 mx-auto mb-2 opacity-40" />
                <p>{t("adminSupport.tickets.selectHint")}</p>
              </div>
            )}
            {selectedTicket && (
              <div className="space-y-4">
                <div className="flex items-start justify-between flex-wrap gap-2 border-b border-white/10 pb-3">
                  <div>
                    <div className="text-[0.65rem] text-neutral-500 font-mono">
                      {t(`support.category.${selectedTicket.category}`)} ·{" "}
                      <span className={`px-1.5 py-0.5 border font-mono ${STATUS_BADGE[selectedTicket.status]}`}>
                        {t(`support.status.${selectedTicket.status}`)}
                      </span>
                    </div>
                    <h3 className="font-display text-lg mt-1">{selectedTicket.subject}</h3>
                    <div className="text-[0.65rem] text-neutral-600 mt-0.5">
                      {selectedTicket.user_name} · {selectedTicket.user_email}
                    </div>
                  </div>
                  {selectedTicket.status !== "closed" && (
                    <Button
                      data-testid="admin-ticket-close"
                      onClick={closeTicket}
                      variant="ghost"
                      className="text-xs border border-white/10 hover:border-[#EF4444]/40 hover:text-[#EF4444] rounded-none h-8"
                    >
                      <X className="w-3.5 h-3.5 mr-1" /> {t("adminSupport.tickets.close")}
                    </Button>
                  )}
                </div>

                <div className="space-y-2 max-h-[45vh] overflow-y-auto">
                  {selectedTicket.messages.map((m) => (
                    <div key={m.id} className={`flex ${m.author_role === "staff" ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[80%] px-3 py-2 border ${
                        m.author_role === "staff"
                          ? "bg-[#22C55E]/5 border-[#22C55E]/30"
                          : "bg-white/[0.03] border-white/10"
                      }`}>
                        <div className="text-[0.6rem] uppercase tracking-wider text-neutral-500 font-mono mb-1">
                          {m.author_role === "staff" ? t("adminSupport.thread.staff") : m.author_name}
                          {" · "}{new Date(m.created_at).toLocaleString()}
                        </div>
                        <div className="text-sm whitespace-pre-wrap break-words">{m.text}</div>
                        {m.images?.length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-2">
                            {m.images.map((src, i) => (
                              <a key={`${src.slice(-40)}-${i}`} href={src} target="_blank" rel="noopener noreferrer">
                                <img src={src} alt="" className="w-16 h-16 object-cover border border-white/10 hover:border-[#8B5CF6]/40" />
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {selectedTicket.status !== "closed" && (
                  <div className="border-t border-white/10 pt-3 space-y-2">
                    <Textarea
                      data-testid="admin-ticket-reply"
                      value={reply}
                      onChange={(e) => setReply(e.target.value)}
                      placeholder={t("adminSupport.thread.replyPlaceholder")}
                      rows={4}
                      maxLength={4000}
                      className="rounded-none bg-[#0a0a0a] border-white/10"
                    />
                    <div className="flex justify-between items-center">
                      <span className="text-[0.6rem] text-neutral-600 font-mono">{reply.length}/4000</span>
                      <Button
                        data-testid="admin-ticket-reply-submit"
                        onClick={submitReply}
                        disabled={replying || !reply.trim()}
                        className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9 text-xs px-5"
                      >
                        <Send className="w-3.5 h-3.5 mr-1.5" />
                        {replying ? t("adminSupport.thread.sending") : t("adminSupport.thread.send")}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "faq" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="text-sm text-neutral-500">
              {t("adminSupport.faq.counter", { total: faq.length })}
            </div>
            <Button
              data-testid="faq-new-btn"
              onClick={startNewFaq}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9 text-xs"
            >
              <Plus className="w-3.5 h-3.5 mr-1.5" /> {t("adminSupport.faq.new")}
            </Button>
          </div>
          {editing && (
            <div className="tactile-card p-4 space-y-3" data-testid="faq-editor">
              <div className="grid md:grid-cols-2 gap-3">
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.faq.category")}</div>
                  <Select value={editing.category} onValueChange={(v) => setEditing({ ...editing, category: v })}>
                    <SelectTrigger data-testid="faq-editor-category" className="rounded-none bg-[#0a0a0a] border-white/10 h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                      {CATEGORIES.map((c) => (
                        <SelectItem key={c} value={c}>{t(`support.category.${c}`)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.faq.order")}</div>
                  <Input
                    data-testid="faq-editor-order"
                    type="number"
                    value={editing.order}
                    onChange={(e) => setEditing({ ...editing, order: e.target.value })}
                    className="rounded-none bg-[#0a0a0a] border-white/10 h-9"
                  />
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.faq.questionEs")}</div>
                  <Input
                    data-testid="faq-editor-question-es"
                    value={editing.question_es}
                    onChange={(e) => setEditing({ ...editing, question_es: e.target.value })}
                    className="rounded-none bg-[#0a0a0a] border-white/10 h-9"
                  />
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.faq.questionEn")}</div>
                  <Input
                    data-testid="faq-editor-question-en"
                    value={editing.question_en}
                    onChange={(e) => setEditing({ ...editing, question_en: e.target.value })}
                    className="rounded-none bg-[#0a0a0a] border-white/10 h-9"
                  />
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.faq.answerEs")}</div>
                  <Textarea
                    data-testid="faq-editor-answer-es"
                    value={editing.answer_es}
                    onChange={(e) => setEditing({ ...editing, answer_es: e.target.value })}
                    rows={4}
                    className="rounded-none bg-[#0a0a0a] border-white/10"
                  />
                </div>
                <div>
                  <div className="micro-label text-neutral-500 mb-1">{t("adminSupport.faq.answerEn")}</div>
                  <Textarea
                    data-testid="faq-editor-answer-en"
                    value={editing.answer_en}
                    onChange={(e) => setEditing({ ...editing, answer_en: e.target.value })}
                    rows={4}
                    className="rounded-none bg-[#0a0a0a] border-white/10"
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 text-xs text-neutral-400 cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="faq-editor-active"
                  checked={!!editing.is_active}
                  onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })}
                />
                {t("adminSupport.faq.isActive")}
              </label>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setEditing(null)}
                  data-testid="faq-editor-cancel"
                  className="text-xs px-3 py-1.5 border border-white/10 hover:border-white/30"
                >
                  {t("adminSupport.faq.cancel")}
                </button>
                <Button
                  data-testid="faq-editor-save"
                  onClick={saveFaq}
                  className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-8 text-xs px-4"
                >
                  {editing.id ? t("adminSupport.faq.saveEdit") : t("adminSupport.faq.saveNew")}
                </Button>
              </div>
            </div>
          )}
          <div className="space-y-2">
            {faq.length === 0 && (
              <div className="tactile-card p-6 text-center text-xs text-neutral-500">
                {t("adminSupport.faq.empty")}
              </div>
            )}
            {faq.map((e) => (
              <div key={e.id} className="tactile-card px-4 py-3 flex items-start gap-3" data-testid={`faq-row-${e.id}`}>
                <div className="flex-1 min-w-0">
                  <div className="text-[0.65rem] text-neutral-500 font-mono uppercase mb-1">
                    {t(`support.category.${e.category}`)} · order {e.order} · {e.is_active ? "active" : "inactive"}
                  </div>
                  <div className="text-sm font-medium">{e.question_es}</div>
                  <div className="text-xs text-neutral-500 truncate">{e.question_en}</div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => startEditFaq(e)}
                    data-testid={`faq-edit-${e.id}`}
                    className="p-1.5 border border-white/10 hover:border-[#8B5CF6]/40 hover:text-[#8B5CF6]"
                    title={t("adminSupport.faq.editBtn")}
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteFaq(e.id)}
                    data-testid={`faq-delete-${e.id}`}
                    className="p-1.5 border border-white/10 hover:border-[#EF4444]/40 hover:text-[#EF4444]"
                    title={t("adminSupport.faq.deleteBtn")}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TabBtn({ id, active, setTab, icon: Icon, label, badge }) {
  const isActive = active === id;
  return (
    <button
      type="button"
      data-testid={`admin-support-tab-${id}`}
      onClick={() => setTab(id)}
      className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 -mb-px transition-colors ${
        isActive
          ? "border-[#8B5CF6] text-white"
          : "border-transparent text-neutral-500 hover:text-white hover:border-white/20"
      }`}
    >
      <Icon className="w-4 h-4" /> {label}
      {badge != null && (
        <span className="ml-1 text-[0.6rem] uppercase tracking-wider bg-[#8B5CF6] text-white px-1.5 py-0.5 min-w-[1.25rem] text-center">
          {badge}
        </span>
      )}
    </button>
  );
}
