/**
 * iter100 — Extracted from Landing.jsx during the code-quality refactor.
 * Sticky top navigation + language switcher + login CTA.
 */
import { useTranslation } from "react-i18next";
import { ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CompactLanguageSwitcher } from "@/components/CompactLanguageSwitcher";
import { ShareAppButton } from "@/components/ShareAppButton";
import { QrShareButton } from "@/components/QrShareButton";

export default function LandingHeader({ user, onEnter, onEmailAuth }) {
  const { t } = useTranslation();
  return (
    <header className="sticky top-0 inset-x-0 z-50 glass-panel">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-12 h-16 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 sm:gap-3 shrink-0 min-w-0">
          <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-10 w-10 sm:h-12 sm:w-12 object-contain" />
          <div className="whitespace-nowrap hidden min-[380px]:block">
            <div className="font-display text-sm leading-none">RESILIENCE</div>
            <div className="micro-label text-neutral-500 text-[0.6rem]">Brothers · P2P</div>
          </div>
        </div>
        <nav className="hidden md:flex items-center gap-8 micro-label text-neutral-400">
          <a href="#about" className="hover:text-white transition-colors">{t("landing.nav.about")}</a>
          <a href="#services" className="hover:text-white transition-colors">{t("landing.nav.services")}</a>
          <a href="#how" className="hover:text-white transition-colors">{t("landing.nav.how")}</a>
          <a href="#vip" className="hover:text-white transition-colors">{t("landing.nav.vip")}</a>
        </nav>
        <div className="flex items-center gap-2 sm:gap-3 shrink min-w-0 justify-end">
          <ShareAppButton
            testid="landing-share-btn"
            url={typeof window !== "undefined" ? window.location.origin : ""}
            text={t("landing.shareText")}
            label={t("landing.shareApp")}
            variant="ghost"
            className="hidden sm:inline-flex items-center text-neutral-400 hover:text-white px-3 h-9 rounded-full border border-white/15 hover:border-violet-400/60 hover:bg-white/5 text-xs"
          />
          <QrShareButton
            testid="landing-qr-btn"
            url={typeof window !== "undefined" ? window.location.origin : ""}
            variant="ghost"
            className="hidden sm:inline-flex items-center text-neutral-400 hover:text-white px-2.5 h-9 rounded-full border border-white/15 hover:border-violet-400/60 hover:bg-white/5"
          />
          <CompactLanguageSwitcher testid="landing-lang-switcher" />
          <Button
            data-testid="header-login-btn"
            onClick={user ? onEnter : onEmailAuth}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none px-3 sm:px-5 h-10 text-sm shrink-0"
          >
            <span className="sm:hidden">
              {user ? t("landing.header.enterPanelShort") : t("landing.header.loginButtonShort")}
            </span>
            <span className="hidden sm:inline">
              {user ? t("landing.header.enterPanel") : t("landing.header.loginButton")}
            </span>
            <ArrowUpRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </div>
    </header>
  );
}
