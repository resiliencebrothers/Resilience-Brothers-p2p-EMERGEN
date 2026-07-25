import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { HelpCircle, Ticket, RefreshCw } from "lucide-react";
import { API } from "@/App";
import { useLiveEvent } from "@/hooks/useLiveStream";
import FAQAccordion from "@/components/support/FAQAccordion";
import NewTicketForm from "@/components/support/NewTicketForm";
import TicketThread from "@/components/support/TicketThread";

/**
 * iter102 — /dashboard/support entrypoint.
 *
 * Three panels stacked:
 *   1. FAQ (loaded from /api/support/faq — admins can CRUD from /admin/support)
 *   2. New-ticket form
 *   3. My tickets (auto-updates via SSE `support_ticket_updated`)
 */
export default function SupportView() {
  const { t } = useTranslation();
  const [faq, setFaq] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("faq"); // "faq" | "new" | "mine"

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [f, mine] = await Promise.all([
        axios.get(`${API}/support/faq`, { withCredentials: true }),
        axios.get(`${API}/support/tickets/me`, { withCredentials: true }),
      ]);
      setFaq(f.data || []);
      setTickets(mine.data || []);
    } catch (e) {
      if (process.env.NODE_ENV !== "production") {
        console.warn("[support] load failed:", e);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // SSE — refresh when staff replies or closes any of my tickets.
  useLiveEvent("support_ticket_updated", (payload) => {
    if (!payload?.ticket_id) return;
    // We only get the summary via SSE; refetch the full thread so the
    // messages list stays complete.
    axios.get(`${API}/support/tickets/me`, { withCredentials: true })
      .then((r) => setTickets(r.data || []))
      .catch(() => {});
  });

  const onTicketCreated = useCallback((ticket) => {
    setTickets((prev) => [ticket, ...prev]);
    setTab("mine");
  }, []);

  const onTicketUpdated = useCallback((ticket) => {
    setTickets((prev) => prev.map((x) => (x.id === ticket.id ? ticket : x)));
  }, []);

  const unreadCount = tickets.filter((x) => x.unread_by_client).length;

  return (
    <div data-testid="support-view" className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("support.eyebrow")}</div>
          <h1 className="font-display text-3xl">{t("support.title")}</h1>
          <p className="text-sm text-neutral-500 mt-1 max-w-2xl">{t("support.subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={loadAll}
          data-testid="support-refresh"
          className="flex items-center gap-1.5 text-xs text-neutral-500 hover:text-[#8B5CF6] transition-colors"
          title={t("support.refresh")}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          {t("support.refresh")}
        </button>
      </div>

      <div className="flex gap-1 border-b border-white/10 -mx-1 px-1">
        <TabButton id="faq" active={tab} setTab={setTab} icon={HelpCircle} label={t("support.tabs.faq")} />
        <TabButton
          id="new" active={tab} setTab={setTab} icon={Ticket}
          label={t("support.tabs.newTicket")}
        />
        <TabButton
          id="mine" active={tab} setTab={setTab} icon={Ticket}
          label={t("support.tabs.myTickets")}
          badge={unreadCount > 0 ? unreadCount : null}
        />
      </div>

      {tab === "faq" && <FAQAccordion entries={faq} />}
      {tab === "new" && <NewTicketForm onCreated={onTicketCreated} />}
      {tab === "mine" && (
        <div className="space-y-3">
          {tickets.length === 0 && (
            <div className="tactile-card p-8 text-center text-sm text-neutral-500" data-testid="tickets-empty">
              {t("support.tickets.empty")}
            </div>
          )}
          {tickets.map((t2) => (
            <TicketThread
              key={t2.id}
              ticket={t2}
              defaultOpen={t2.unread_by_client}
              onUpdated={onTicketUpdated}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TabButton({ id, active, setTab, icon: Icon, label, badge }) {
  const isActive = active === id;
  return (
    <button
      type="button"
      data-testid={`support-tab-${id}`}
      onClick={() => setTab(id)}
      className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors -mb-px ${
        isActive
          ? "border-[#8B5CF6] text-white"
          : "border-transparent text-neutral-500 hover:text-white hover:border-white/20"
      }`}
    >
      <Icon className="w-4 h-4" />
      {label}
      {badge != null && (
        <span className="ml-1 text-[0.6rem] uppercase tracking-wider bg-[#8B5CF6] text-white px-1.5 py-0.5 min-w-[1.25rem] text-center">
          {badge}
        </span>
      )}
    </button>
  );
}
