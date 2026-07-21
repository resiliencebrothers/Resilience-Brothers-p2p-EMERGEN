/**
 * iter85 — BlockContactDialog
 *
 * Single-contact create dialog with phone/name/email/reason/notes form.
 * Presentation-only — form state + save handler live in useBlockedContacts.
 */
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

export default function BlockContactDialog({ open, setOpen, form, setForm, saving, onSubmit }) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        data-testid="block-contact-dialog"
        className="bg-[#14101F] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">
            {t("admin.blocked.blockDialogTitle")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label className="micro-label text-neutral-500">{t("admin.blocked.phoneLabel")}</Label>
            <Input
              data-testid="block-phone-input"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              placeholder="+5350123456"
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("admin.blocked.nameLabel")}</Label>
            <Input
              data-testid="block-name-input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={t("admin.blocked.namePh")}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("admin.blocked.emailLabel")}</Label>
            <Input
              data-testid="block-email-input"
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder={t("admin.blocked.emailPh")}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
            />
          </div>
          <p className="text-[0.65rem] text-neutral-600 -mt-2">
            {t("admin.blocked.atLeastOne")}
          </p>
          <div>
            <Label className="micro-label text-neutral-500">{t("admin.blocked.reasonLabel")}</Label>
            <Input
              data-testid="block-reason-input"
              required
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              placeholder={t("admin.blocked.reasonPh")}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("admin.blocked.notesLabel")}</Label>
            <Textarea
              data-testid="block-notes-input"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder={t("admin.blocked.notesPh")}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[80px]"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="ghost"
              onClick={() => setOpen(false)}
              className="rounded-none"
            >
              {t("admin.blocked.cancel")}
            </Button>
            <Button
              data-testid="block-submit"
              onClick={onSubmit}
              disabled={saving}
              className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none"
            >
              {saving ? t("admin.blocked.blocking") : t("admin.blocked.block")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
