import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { MessageCircle, Send, Lock } from "lucide-react";
import { useLiveEvent } from "@/hooks/useLiveStream";

// iter210 — Chat cliente ↔ mensajero dentro de la app (sin compartir
// números personales). Se usa desde el tracker del cliente y desde el
// panel del mensajero. Tiempo real vía SSE + polling de respaldo.

function fmtTime(isoStr) {
  try {
    return new Date(isoStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function DeliveryChatDialog({ deliveryId, open, onClose }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  const load = useCallback(() => {
    if (!deliveryId) return;
    axios.get(`${API}/deliveries/${deliveryId}/chat`, { withCredentials: true })
      .then((r) => setData(r.data))
      .catch(() => {});
  }, [deliveryId]);

  useEffect(() => {
    if (!open) return undefined;
    load();
    const iv = setInterval(load, 8000);
    return () => clearInterval(iv);
  }, [open, load]);

  useLiveEvent("delivery_chat_message", (e) => {
    if (open && e?.delivery_id === deliveryId) load();
  });

  const msgCount = data?.messages?.length || 0;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgCount]);

  const send = async () => {
    const val = text.trim();
    if (!val || busy) return;
    setBusy(true);
    try {
      await axios.post(`${API}/deliveries/${deliveryId}/chat`,
        { text: val }, { withCredentials: true });
      setText("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    } finally {
      setBusy(false);
    }
  };

  const otherName = data
    ? (data.my_kind === "client" ? data.courier_name : data.client_name)
    : "";

  return (
    <Dialog open={!!open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="delivery-chat-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-md p-0 gap-0 max-h-[85vh] overflow-hidden"
      >
        <DialogHeader className="px-4 pt-4 pb-3 border-b border-white/5">
          <DialogTitle className="flex items-center gap-2 text-base">
            <MessageCircle className="w-5 h-5 text-[#8B5CF6]" />
            {otherName
              ? t("deliveryChat.with", { name: otherName })
              : t("deliveryChat.title")}
          </DialogTitle>
        </DialogHeader>

        <div
          className="px-4 py-3 space-y-2 max-h-[50vh] min-h-[180px] overflow-y-auto"
          data-testid="delivery-chat-messages"
        >
          {(data?.messages || []).length === 0 && (
            <p className="text-xs text-neutral-500 text-center py-8" data-testid="delivery-chat-empty">
              {t("deliveryChat.empty")}
            </p>
          )}
          {(data?.messages || []).map((m) => {
            const mine = data && m.sender_kind === data.my_kind;
            return (
              <div
                key={m.id}
                className={`flex ${mine ? "justify-end" : "justify-start"}`}
                data-testid={`chat-msg-${m.id}`}
              >
                <div className={`max-w-[80%] px-3 py-2 text-sm ${
                  mine
                    ? "bg-[#8B5CF6]/20 border border-[#8B5CF6]/40"
                    : "bg-white/[0.04] border border-white/10"
                }`}>
                  {!mine && (
                    <div className="text-[0.65rem] text-[#A78BFA] mb-0.5">{m.sender_name}</div>
                  )}
                  <div className="whitespace-pre-wrap break-words">{m.text}</div>
                  <div className="text-[0.6rem] text-neutral-500 text-right mt-1 font-mono">
                    {fmtTime(m.created_at)}
                  </div>
                </div>
              </div>
            );
          })}
          <div ref={endRef} />
        </div>

        {data && !data.can_send ? (
          <div
            className="px-4 py-3 border-t border-white/5 text-xs text-neutral-500 flex items-center gap-2"
            data-testid="delivery-chat-closed"
          >
            <Lock className="w-3.5 h-3.5" /> {t("deliveryChat.closed")}
          </div>
        ) : (
          <div className="flex gap-2 px-4 py-3 border-t border-white/5">
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              maxLength={500}
              placeholder={t("deliveryChat.placeholder")}
              data-testid="delivery-chat-input"
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 text-sm"
            />
            <Button
              onClick={send}
              disabled={busy || !text.trim()}
              data-testid="delivery-chat-send-btn"
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-10 px-4 disabled:opacity-40"
            >
              <Send className="w-4 h-4" />
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
