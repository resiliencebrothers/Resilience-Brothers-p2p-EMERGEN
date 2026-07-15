import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { MessageSquare, Send, Loader2, CheckCircle2, XCircle, Clock } from "lucide-react";
import { extractDetailMessage } from "@/utils/apiErrors";

/**
 * AppealDialog — self-service appeal for `under_review` clients.
 */
export default function AppealDialog() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/appeals/me`, { withCredentials: true });
      setItems(r.data.items || []);
    } catch (e) {
      toast.error(extractDetailMessage(e, t("appeal.loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const hasPending = items.some((a) => a.status === "pending");

  const submit = async () => {
    const trimmed = message.trim();
    if (trimmed.length < 10) {
      toast.error(t("appeal.errTooShort"));
      return;
    }
    setSending(true);
    try {
      await axios.post(
        `${API}/appeals`,
        { message: trimmed },
        { withCredentials: true }
      );
      toast.success(t("appeal.successToast"));
      setMessage("");
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail?.code === "APPEAL_ALREADY_PENDING") {
        toast.error(t("appeal.errAlreadyPending"));
        await load();
      } else {
        toast.error(extractDetailMessage(e, t("appeal.errSubmit")));
      }
    } finally {
      setSending(false);
    }
  };

  const statusChip = (status) => {
    const config = {
      pending: { icon: Clock, cls: "text-[#8B5CF6] border-[#8B5CF6]/40 bg-[#8B5CF6]/5", label: t("appeal.statusPending") },
      resolved: { icon: CheckCircle2, cls: "text-[#22C55E] border-[#22C55E]/40 bg-[#22C55E]/5", label: t("appeal.statusResolved") },
      rejected: { icon: XCircle, cls: "text-[#EF4444] border-[#EF4444]/40 bg-[#EF4444]/5", label: t("appeal.statusRejected") },
    }[status] || { icon: Clock, cls: "text-neutral-400 border-white/10", label: status };
    const Icon = config.icon;
    return (
      <span className={`inline-flex items-center gap-1.5 text-[0.65rem] tracking-wider font-semibold border px-2 py-0.5 uppercase ${config.cls}`}>
        <Icon className="w-3 h-3" /> {config.label}
      </span>
    );
  };

  return (
    <>
      <Button
        data-testid="open-appeal-dialog-btn"
        onClick={() => setOpen(true)}
        variant="outline"
        size="sm"
        className="border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 mt-3"
      >
        <MessageSquare className="w-3.5 h-3.5 mr-1.5" />
        {t("appeal.openBtn")}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="appeal-dialog" className="max-w-lg bg-[#0c0c0c] border-white/10 text-white max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-white">{t("appeal.dialogTitle")}</DialogTitle>
            <DialogDescription className="text-neutral-400 text-xs leading-relaxed">
              {t("appeal.dialogDescription")}
            </DialogDescription>
          </DialogHeader>

          {!hasPending && (
            <div className="space-y-2">
              <Textarea
                data-testid="appeal-message-textarea"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={t("appeal.textareaPlaceholder")}
                rows={5}
                maxLength={2000}
                className="bg-black/40 border-white/10 text-sm text-white"
              />
              <div className="flex items-center justify-between text-[0.65rem] text-neutral-500">
                <span>{message.length}/2000</span>
                <span>{message.trim().length < 10 ? t("appeal.charsRemaining", { n: 10 - message.trim().length }) : t("appeal.readyToSend")}</span>
              </div>
            </div>
          )}

          {hasPending && (
            <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 px-3 py-2.5 text-xs text-[#FEF3C7]">
              {t("appeal.alreadyPendingBanner")}
            </div>
          )}

          <div className="border-t border-white/5 pt-3">
            <div className="micro-label text-neutral-500 text-[0.65rem] mb-2">{t("appeal.historyHeading")}</div>
            {loading && <div className="text-xs text-neutral-500">{t("appeal.loadingHistory")}</div>}
            {!loading && items.length === 0 && (
              <div className="text-xs text-neutral-500 italic">{t("appeal.historyEmpty")}</div>
            )}
            {!loading && items.length > 0 && (
              <ul className="space-y-2 max-h-56 overflow-y-auto pr-1">
                {items.map((a) => (
                  <li key={a.id} data-testid={`appeal-history-item-${a.id}`} className="border border-white/5 bg-black/30 px-3 py-2 space-y-1">
                    <div className="flex items-center justify-between">
                      {statusChip(a.status)}
                      <span className="text-[0.6rem] text-neutral-500">{a.created_at?.slice(0, 16).replace("T", " ")}</span>
                    </div>
                    <div className="text-xs text-neutral-300 line-clamp-3">{a.message}</div>
                    {a.staff_response && (
                      <div className="text-[0.7rem] text-neutral-400 border-l-2 border-[#8B5CF6]/60 pl-2 mt-1">
                        <span className="text-[#8B5CF6] font-semibold">{t("appeal.staffPrefix")}: </span>{a.staff_response}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <DialogFooter className="pt-2">
            <Button
              variant="ghost"
              onClick={() => setOpen(false)}
              data-testid="appeal-close-btn"
              className="text-neutral-400 hover:text-white"
            >
              {t("appeal.close")}
            </Button>
            {!hasPending && (
              <Button
                data-testid="appeal-submit-btn"
                onClick={submit}
                disabled={sending || message.trim().length < 10}
                className="bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white font-semibold"
              >
                {sending ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Send className="w-4 h-4 mr-1.5" />}
                {t("appeal.send")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
