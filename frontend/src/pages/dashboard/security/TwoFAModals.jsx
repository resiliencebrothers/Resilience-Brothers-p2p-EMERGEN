import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

/**
 * Two lightweight step-up 2FA modals: "Disable 2FA" and "Regenerate recovery
 * codes". Both share the same shape (title + body + 6-digit code input +
 * cancel/confirm).
 */
export function DisableTwoFAModal({ open, onOpenChange, code, onCodeChange, onConfirm, busy }) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("security.disableDialog.title")}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-neutral-400">{t("security.disableDialog.body")}</p>
        <Input
          data-testid="security-disable-input"
          value={code}
          onChange={(e) => onCodeChange(e.target.value)}
          placeholder={t("security.disableDialog.placeholder")}
          className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono"
        />
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} className="rounded-none bg-transparent border border-white/15 text-white">
            {t("security.disableDialog.cancel")}
          </Button>
          <Button
            data-testid="security-disable-confirm"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-none bg-[#EF4444] hover:bg-[#EF4444]/90 text-white font-bold"
          >
            {t("security.disableDialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RegenerateCodesModal({ open, onOpenChange, code, onCodeChange, onConfirm, busy }) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("security.regenDialog.title")}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-neutral-400">{t("security.regenDialog.body")}</p>
        <Input
          value={code}
          onChange={(e) => onCodeChange(e.target.value)}
          placeholder={t("security.regenDialog.placeholder")}
          className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono"
        />
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} className="rounded-none bg-transparent border border-white/15 text-white">
            {t("security.regenDialog.cancel")}
          </Button>
          <Button
            onClick={onConfirm}
            disabled={busy}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold"
          >
            {t("security.regenDialog.regenerate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
