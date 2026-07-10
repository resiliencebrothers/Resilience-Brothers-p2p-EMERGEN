import { useAuth } from "@/context/AuthContext";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Bell, CheckCheck, UserCheck, UserX, BellRing, X, Trash2, ExternalLink } from "lucide-react";
import { useState } from "react";
import { useNotifications } from "@/hooks/useNotifications";

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

/* ----------------- sub-components ----------------- */

function NotificationRow({ item, onClick, onDelete }) {
  const { Icon, color } = TYPE_ICON[item.type] || TYPE_ICON.info;
  const explorerUrl = item.data?.explorer_url;
  const network = item.data?.crypto_network;
  return (
    <div
      className={`group relative w-full border-b border-white/5 hover:bg-white/[0.02] transition-colors ${item.read ? "opacity-60" : ""}`}
    >
      <button
        type="button"
        data-testid={`notification-item-${item.id}`}
        onClick={onClick}
        className="w-full text-left px-4 py-3 pr-10 flex gap-3"
      >
        <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${color}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-xs font-semibold text-neutral-200 truncate">{item.title}</span>
            <span className="text-[0.6rem] text-neutral-600 flex-shrink-0">{timeAgo(item.created_at)}</span>
          </div>
          <p className="text-[0.7rem] text-neutral-400 mt-0.5 line-clamp-2">{item.message}</p>
          {explorerUrl && (
            <a
              href={explorerUrl}
              target="_blank"
              rel="noopener noreferrer"
              data-testid={`notification-explorer-${item.id}`}
              onClick={(e) => e.stopPropagation()}
              className="mt-2 inline-flex items-center gap-1 text-[0.65rem] font-mono uppercase tracking-wider text-[#EAB308] hover:text-[#FACC15] hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              <span>Verificar en {network || "explorer"}</span>
            </a>
          )}
        </div>
        {!item.read && <span className="w-2 h-2 rounded-full bg-[#EAB308] mt-1.5 flex-shrink-0" />}
      </button>
      <button
        type="button"
        data-testid={`notification-delete-${item.id}`}
        onClick={(e) => { e.stopPropagation(); onDelete(item.id); }}
        title="Eliminar notificación"
        aria-label="Eliminar notificación"
        className="absolute right-2 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center text-neutral-600 hover:text-[#EF4444] hover:bg-[#EF4444]/10 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

function NotificationList({ items, loading, onItemClick, onDelete }) {
  if (loading) {
    return <div className="py-10 text-center text-xs text-neutral-500">Cargando...</div>;
  }
  if (items.length === 0) {
    return (
      <div className="py-12 text-center" data-testid="notifications-empty">
        <Bell className="w-8 h-8 text-neutral-700 mx-auto mb-2" />
        <p className="text-xs text-neutral-500">No tienes notificaciones todavía.</p>
      </div>
    );
  }
  return items.map((it) => (
    <NotificationRow
      key={it.id}
      item={it}
      onClick={() => !it.read && onItemClick(it.id)}
      onDelete={onDelete}
    />
  ));
}

/* ----------------- main component ----------------- */

export default function NotificationBell() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const {
    unreadCount, items, loading, loadList,
    markRead, markAllRead, deleteOne, deleteAllRead,
  } = useNotifications();

  const handleOpen = (next) => {
    setOpen(next);
    if (next) loadList();
  };

  if (!user) return null;

  const hasUnread = items.some((it) => !it.read);
  const hasRead = items.some((it) => it.read);

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
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 gap-2">
          <div className="min-w-0">
            <h3 className="font-display text-base">Notificaciones</h3>
            <p className="text-[0.65rem] text-neutral-500">{unreadCount > 0 ? `${unreadCount} sin leer` : "Todo al día"}</p>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {hasUnread && (
              <button
                type="button"
                data-testid="mark-all-read-btn"
                onClick={markAllRead}
                className="text-[0.65rem] uppercase tracking-widest text-[#EAB308] hover:text-[#FACC15] flex items-center gap-1"
              >
                <CheckCheck className="w-3 h-3" /> Marcar todo
              </button>
            )}
            {hasRead && (
              <button
                type="button"
                data-testid="delete-all-read-btn"
                onClick={deleteAllRead}
                title="Eliminar todas las notificaciones leídas"
                className="text-[0.65rem] uppercase tracking-widest text-neutral-500 hover:text-[#EF4444] flex items-center gap-1"
              >
                <Trash2 className="w-3 h-3" /> Borrar leídas
              </button>
            )}
          </div>
        </div>
        <ScrollArea className="max-h-[420px]">
          <NotificationList items={items} loading={loading} onItemClick={markRead} onDelete={deleteOne} />
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
