import { useTranslation } from "react-i18next";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Keyboard } from "lucide-react";

/**
 * Keyboard-shortcut cheat sheet. Small dialog opened by pressing "?" or
 * clicking the "Shortcuts" button in the AdminKYC toolbar.
 */
export default function KYCHelpDialog({ open, onOpenChange }) {
  const { t } = useTranslation();
  const hints = [
    { keys: ["J", "↓"],     label: t("admin.kycAdmin.kbdNext") },
    { keys: ["K", "↑"],     label: t("admin.kycAdmin.kbdPrev") },
    { keys: ["A"],          label: t("admin.kycAdmin.kbdApprove") },
    { keys: ["R"],          label: t("admin.kycAdmin.kbdReject") },
    { keys: ["I"],          label: t("admin.kycAdmin.kbdMoreInfo") },
    { keys: ["X"],          label: t("admin.kycAdmin.kbdToggle") },
    { keys: ["Shift", "A"], label: t("admin.kycAdmin.kbdBulkApprove") },
    { keys: ["Enter"],      label: t("admin.kycAdmin.kbdConfirmDialog") },
    { keys: ["Esc"],        label: t("admin.kycAdmin.kbdCloseDialog") },
    { keys: ["?"],          label: t("admin.kycAdmin.kbdShowHelp") },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-neutral-950 border-white/10 max-w-md max-h-[85vh] overflow-y-auto"
        data-testid="kyc-help-dialog"
      >
        <DialogHeader>
          <DialogTitle className="text-white flex items-center gap-2">
            <Keyboard className="w-5 h-5 text-[#8B5CF6]" />
            {t("admin.kycAdmin.shortcutsTitle")}
          </DialogTitle>
          <DialogDescription className="text-neutral-500">
            {t("admin.kycAdmin.shortcutsDesc")}
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-2">
          {hints.map(({ keys, label }) => (
            <li key={label} className="flex items-center justify-between gap-4 text-sm">
              <span className="text-neutral-300">{label}</span>
              <span className="flex gap-1 items-center">
                {keys.map((k) => (
                  <span key={`${label}-${k}`} className="flex items-center gap-1">
                    {k !== keys[0] && <span className="text-neutral-500 text-xs">+</span>}
                    <kbd className="kbd">{k}</kbd>
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
