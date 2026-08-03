import { useCallback, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Send, ChevronDown, MessageCircle, Clock, CheckCircle2, XCircle } from "lucide-react";
import { API } from "@/App";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

const STATUS_META = {
  open: { icon: Clock, color: "text-[#EAB308]", bg: "bg-[#EAB308]/10 border-[#EAB308]/40" },
  answered: { icon: CheckCircle2, color: "text-[#22C55E]", bg: "bg-[#22C55E]/10 border-[#22C55E]/40" },
  closed: { icon: XCircle, color: "text-neutral-500", bg: "bg-neutral-500/10 border-neutral-500/30" },
};

/**
 * iter102 — One row in "Mis tickets". Click to expand → shows the whole
 * conversation. If status !== closed, the client can post a reply.
 *
 * On reply: PATCHes local state via `onUpdated(updatedTicket)` so we don't
 * refetch the whole list.
 */
export default function TicketThread({ ticket, defaultOpen = false, onUpdated }) {
  const { t, i18n } = useTranslation();
  const lang = (i18n.language || "es").startsWith("en") ? "en" : "es";
  const [open, setOpen] = useState(defaultOpen);
  const [reply, setReply] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const meta = STATUS_META[ticket.status] || STATUS_META.open;
  const StatusIcon = meta.icon;
  const isClosed = ticket.status === "closed";
  const hasUnread = ticket.unread_by_client;

  const submitReply = useCallback(async () => {
    if (!reply.trim()) return;
    setSubmitting(true);
    try {
      const r = await axios.post(
        `${API}/support/tickets/${ticket.id}/reply`,
        { text: reply.trim(), images: [] },
        { withCredentials: true },
      );
      toast.success(t("support.thread.replySent"));
      setReply("");
      onUpdated?.(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("support.thread.replyFailed"));
    } finally {
      setSubmitting(false);
    }
  }, [reply, ticket.id, t, onUpdated]);

  const toggleOpen = useCallback(async () => {
    const next = !open;
    setOpen(next);
    if (next && hasUnread) {
      try {
        await axios.post(`${API}/support/tickets/${ticket.id}/mark-read`,
                         {}, { withCredentials: true });
        onUpdated?.({ ...ticket, unread_by_client: false });
      } catch { /* silent */ }
    }
  }, [open, hasUnread, ticket, onUpdated]);

  return (
    <div
      data-testid={`ticket-${ticket.id}`}
      className={`tactile-card overflow-hidden ${hasUnread ? "ring-1 ring-[#8B5CF6]/40" : ""}`}
    >
      <button
        type="button"
        onClick={toggleOpen}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors text-left"
        data-testid={`ticket-toggle-${ticket.id}`}
      >
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[0.6rem] uppercase tracking-wider border font-mono ${meta.bg} ${meta.color}`}>
          <StatusIcon className="w-3 h-3" />
          {t(`support.status.${ticket.status}`)}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm truncate">{ticket.subject}</div>
          <div className="text-[0.65rem] text-neutral-600 font-mono mt-0.5">
            {t(`support.category.${ticket.category}`)} · {new Date(ticket.updated_at).toLocaleString()}
          </div>
        </div>
        {hasUnread && (
          <span className="text-[0.6rem] uppercase tracking-wider bg-[#8B5CF6] text-white px-1.5 py-0.5">
            {t("support.thread.newBadge")}
          </span>
        )}
        <ChevronDown className={`w-4 h-4 text-neutral-500 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="border-t border-white/5 bg-black/40">
          <div className="p-4 space-y-3">
            {ticket.messages.map((m) => (
              <div
                key={m.id}
                data-testid={`ticket-msg-${m.id}`}
                className={`flex ${m.author_role === "client" ? "justify-end" : "justify-start"}`}
              >
                <div className={`max-w-[80%] px-3 py-2 border ${
                  m.author_role === "client"
                    ? "bg-[#8B5CF6]/10 border-[#8B5CF6]/30"
                    : "bg-white/[0.03] border-white/10"
                }`}>
                  <div className="text-[0.6rem] uppercase tracking-wider text-neutral-500 font-mono mb-1">
                    {m.author_role === "client" ? t("support.thread.you") : (m.author_name || t("support.thread.staff"))}
                    {" · "}
                    <span>{new Date(m.created_at).toLocaleString(lang === "en" ? "en-US" : "es-ES")}</span>
                  </div>
                  <div className="text-sm whitespace-pre-wrap break-words">{m.text}</div>
                  {m.images?.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {m.images.map((src, i) => (
                        <a key={`${src.slice(-40)}-${i}`} href={src} target="_blank" rel="noopener noreferrer" className="block">
                          <img
                            src={src}
                            alt={`attachment-${i}`}
                            className="w-16 h-16 object-cover border border-white/10 hover:border-[#8B5CF6]/50 transition-colors"
                          />
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {!isClosed && (
            <div className="p-4 border-t border-white/5">
              <Textarea
                data-testid={`ticket-reply-${ticket.id}`}
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder={t("support.thread.replyPlaceholder")}
                rows={3}
                maxLength={4000}
                className="rounded-none bg-[#0a0a0a] border-white/10 mb-2"
              />
              <div className="flex items-center justify-between">
                <span className="text-[0.65rem] text-neutral-600 font-mono">
                  {reply.length}/4000
                </span>
                <Button
                  data-testid={`ticket-reply-submit-${ticket.id}`}
                  onClick={submitReply}
                  disabled={submitting || !reply.trim()}
                  className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none px-4 h-9 text-xs"
                >
                  <Send className="w-3.5 h-3.5 mr-1.5" />
                  {submitting ? t("support.thread.sending") : t("support.thread.sendReply")}
                </Button>
              </div>
            </div>
          )}

          {isClosed && (
            <div className="p-4 border-t border-white/5 text-center text-xs text-neutral-500">
              <MessageCircle className="w-4 h-4 inline mr-1.5" />
              {t("support.thread.closedNote")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
