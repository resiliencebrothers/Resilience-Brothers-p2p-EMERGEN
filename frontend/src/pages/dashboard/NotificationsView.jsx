import { useTranslation, Trans } from "react-i18next";
import ProfileSectionTabs from "@/components/ProfileSectionTabs";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import PushToggle from "@/components/PushToggle";
import { Bell, Info } from "lucide-react";

/**
 * iter55.32 — Notifications tab inside "Mi Perfil".
 * iter55.33 — Also hosts the language switcher (Preferencias del cliente).
 */
export default function NotificationsView() {
  const { t } = useTranslation();
  return (
    <div className="space-y-6" data-testid="notifications-view">
      <ProfileSectionTabs />

      <div className="tactile-card p-6" data-testid="push-notifications-block">
        <div className="flex items-start gap-3 mb-5">
          <div className="w-10 h-10 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
            <Bell className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h2 className="font-display text-xl">{t("notifications.pushTitle")}</h2>
            <p className="text-sm text-neutral-500 mt-1">
              {t("notifications.pushDescription")}
            </p>
          </div>
        </div>

        <PushToggle />

        <div className="mt-6 border-t border-white/5 pt-4">
          <div className="flex items-start gap-2 text-xs text-neutral-500 leading-relaxed">
            <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-violet-400/70" />
            <span>
              <Trans i18nKey="notifications.iosHint" />
            </span>
          </div>
        </div>
      </div>

      <div className="tactile-card p-6" data-testid="language-block">
        <LanguageSwitcher />
      </div>
    </div>
  );
}
