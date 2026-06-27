import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Bell, CheckCheck, UserCheck, UserX, BellRing } from "lucide-react";

const POLL_MS = 30_000;

const TYPE_ICON = {
  new_user_pending: { Icon: UserCheck, color: "text-[#EAB308]" },
  phone_verified: { Icon: UserCheck, color: "text-[#22C55E]" },
  phone_rejected: { Icon: UserX, color: "text-[#EF4444]" },
  info: { Icon: BellRing, color: "text-neutral-400" },
};

function timeAgo(iso) {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "ahora";
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)}h`;
  return `hace ${Math.floor(seconds / 86400)}d`;
}

export default function NotificationBell() {
  const { user } = useAuth();
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef(null);

  const refreshCount = useCallback(async () => {
    if (!user) return;
    try {
      const r = await axios.get(`${API}/notifications/unread-count`, { withCredentials: true });
      setUnreadCount(r.data?.count || 0);
    } catch (e) { /* silent — bell not blocking */ }
  }, [user]);

  const loadList = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const r = await axios.get(`${API}/notifications`, { withCredentials: true, params: { limit: 30 } });
      setItems(r.data?.items || []);
    } catch (e) { /* silent */ } finally { setLoading(false); }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    refreshCount();
    pollRef.current = setInterval(refreshCount, POLL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [user, refreshCount]);

  // When opening, fetch the latest list and mark items as read implicitly on click.
  const handleOpen = (next) => {
    setOpen(next);
    if (next) loadList();
  };

  const markRead = async (id) => {
    try {
      await axios.post(`${API}/notifications/${id}/read`, {}, { withCredentials: true });
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, read: true } : it)));
      refreshCount();
    } catch (e) { /* silent */ }
  };

  const markAllRead = async () => {
    try {
      await axios.post(`${API}/notifications/mark-all-read`, {}, { withCredentials: true });
      setItems((prev) => prev.map((it) => ({ ...it, read: true })));
      setUnreadCount(0);
    } catch (e) { /* silent */ }
  };

  if (!user) return null;

  return (
    <Popover open={open} onOpenChange={handleOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="notification-bell"
          className="relative inline-flex items-center justify-center w-9 h-9 hover:bg-white/5 transition-colors"
          aria-label="Notificaciones"
        >
          <Bell className="w-5 h-5 text-neutral-400" />
          {unreadCount > 0 && (
            <span
              data-testid="notification-unread-badge"
              className="absolute top-1 right-1 min-w-[18px] h-[18px] px-1 flex items-center justify-center bg-[#EF4444] text-white text-[0.65rem] font-bold rounded-full ring-2 ring-[#0a0a0a]"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[380px] p-0 bg-[#0A0A0A] border-white/10 text-white rounded-none"
        data-testid="notifications-popover"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
          <div>
            <h3 className="font-display text-base">Notificaciones</h3>
            <p className="text-[0.65rem] text-neutral-500">{unreadCount > 0 ? `${unreadCount} sin leer` : "Todo al día"}</p>
          </div>
          {items.some((it) => !it.read) && (
            <button
              type="button"
              data-testid="mark-all-read-btn"
              onClick={markAllRead}
              className="text-[0.65rem] uppercase tracking-widest text-[#EAB308] hover:text-[#FACC15] flex items-center gap-1"
            >
              <CheckCheck className="w-3 h-3" /> Marcar todo
            </button>
          )}
        </div>
        <ScrollArea className="max-h-[420px]">
          {loading && <div className="py-10 text-center text-xs text-neutral-500">Cargando...</div>}
          {!loading && items.length === 0 && (
            <div className="py-12 text-center" data-testid="notifications-empty">
              <Bell className="w-8 h-8 text-neutral-700 mx-auto mb-2" />
              <p className="text-xs text-neutral-500">No tienes notificaciones todavía.</p>
            </div>
          )}
          {!loading && items.map((it) => {
            const { Icon, color } = TYPE_ICON[it.type] || TYPE_ICON.info;
            return (
              <button
                key={it.id}
                type="button"
                data-testid={`notification-item-${it.id}`}
                onClick={() => !it.read && markRead(it.id)}
                className={`w-full text-left px-4 py-3 border-b border-white/5 hover:bg-white/[0.02] transition-colors flex gap-3 ${it.read ? "opacity-60" : ""}`}
              >
                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${color}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-xs font-semibold text-neutral-200 truncate">{it.title}</span>
                    <span className="text-[0.6rem] text-neutral-600 flex-shrink-0">{timeAgo(it.created_at)}</span>
                  </div>
                  <p className="text-[0.7rem] text-neutral-400 mt-0.5 line-clamp-2">{it.message}</p>
                </div>
                {!it.read && <span className="w-2 h-2 rounded-full bg-[#EAB308] mt-1.5 flex-shrink-0" />}
              </button>
            );
          })}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
