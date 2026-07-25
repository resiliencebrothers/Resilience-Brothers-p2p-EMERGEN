import { useCallback, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Send, X, Upload } from "lucide-react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { fileToDataUrl, isImageTooLarge } from "@/utils/fileToDataUrl";

const CATEGORIES = ["general", "kyc", "convert", "withdrawal", "fees", "other"];
const MAX_IMAGES = 3;

/**
 * iter102 — "Abrir nuevo ticket" form. Fields:
 *   • category (Select) · required
 *   • subject (Input, max 120 chars) · required
 *   • message (Textarea, 5–4000 chars) · required
 *   • up to 3 image attachments (base64 → R2)
 *
 * On success: reset form + `onCreated(ticket)` so the parent prepends the
 * new ticket to the list without a network round-trip.
 */
export default function NewTicketForm({ onCreated }) {
  const { t } = useTranslation();
  const [category, setCategory] = useState("general");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [images, setImages] = useState([]); // [{name, dataUrl}]
  const [submitting, setSubmitting] = useState(false);

  const handleFiles = useCallback(async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    e.target.value = "";
    for (const file of files) {
      if (images.length >= MAX_IMAGES) {
        toast.warning(t("support.ticket.imageLimitReached", { max: MAX_IMAGES }));
        break;
      }
      if (isImageTooLarge(file)) {
        toast.error(t("support.ticket.imageTooLarge", { name: file.name }));
        continue;
      }
      try {
        const dataUrl = await fileToDataUrl(file);
        setImages((prev) => [...prev, { name: file.name, dataUrl }]);
      } catch {
        toast.error(t("support.ticket.imageReadFailed"));
      }
    }
  }, [images.length, t]);

  const removeImage = (i) => setImages((prev) => prev.filter((_, idx) => idx !== i));

  const submit = async () => {
    if (!subject.trim() || !message.trim()) {
      toast.error(t("support.ticket.missingFields"));
      return;
    }
    setSubmitting(true);
    try {
      const r = await axios.post(
        `${API}/support/tickets`,
        {
          category,
          subject: subject.trim(),
          message: message.trim(),
          images: images.map((i) => i.dataUrl),
        },
        { withCredentials: true },
      );
      toast.success(t("support.ticket.created"));
      setSubject(""); setMessage(""); setImages([]); setCategory("general");
      onCreated?.(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : t("support.ticket.createFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="tactile-card p-6 space-y-4" data-testid="new-ticket-form">
      <div className="micro-label text-[#8B5CF6] mb-2">{t("support.newTicket.eyebrow")}</div>
      <h3 className="font-display text-xl">{t("support.newTicket.title")}</h3>
      <p className="text-sm text-neutral-500">{t("support.newTicket.subtitle")}</p>

      <div className="grid gap-4">
        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("support.newTicket.category")}</div>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger data-testid="ticket-category" className="rounded-none bg-[#0a0a0a] border-white/10 h-10">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c} data-testid={`ticket-category-${c}`}>
                  {t(`support.category.${c}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("support.newTicket.subject")}</div>
          <Input
            data-testid="ticket-subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            maxLength={120}
            placeholder={t("support.newTicket.subjectPlaceholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 h-10"
          />
        </div>

        <div>
          <div className="micro-label text-neutral-500 mb-1">{t("support.newTicket.message")}</div>
          <Textarea
            data-testid="ticket-message"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={4000}
            rows={5}
            placeholder={t("support.newTicket.messagePlaceholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10"
          />
          <div className="text-[0.65rem] text-neutral-600 mt-1 text-right font-mono">
            {message.length}/4000
          </div>
        </div>

        <div>
          <div className="micro-label text-neutral-500 mb-1">
            {t("support.newTicket.images")}{" "}
            <span className="text-neutral-600">({images.length}/{MAX_IMAGES})</span>
          </div>
          <label className="inline-flex items-center gap-2 px-3 py-2 border border-white/10 hover:border-[#8B5CF6]/40 hover:bg-[#8B5CF6]/5 text-xs cursor-pointer transition-colors">
            <Upload className="w-3.5 h-3.5" />
            <span>{t("support.newTicket.uploadImages")}</span>
            <input
              data-testid="ticket-file-input"
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={handleFiles}
              disabled={images.length >= MAX_IMAGES}
            />
          </label>
          {images.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {images.map((img, i) => (
                <div key={img.name + i} className="relative w-16 h-16 border border-white/10 overflow-hidden group">
                  <img src={img.dataUrl} alt={img.name} className="object-cover w-full h-full" />
                  <button
                    type="button"
                    onClick={() => removeImage(i)}
                    data-testid={`ticket-image-remove-${i}`}
                    className="absolute top-0.5 right-0.5 bg-black/70 hover:bg-[#EF4444]/80 p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <Button
        data-testid="ticket-submit"
        onClick={submit}
        disabled={submitting || !subject.trim() || !message.trim()}
        className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none px-6 h-11"
      >
        <Send className="w-4 h-4 mr-2" />
        {submitting ? t("support.newTicket.sending") : t("support.newTicket.submit")}
      </Button>
    </div>
  );
}
