/**
 * iter100 — Extracted from Landing.jsx during the code-quality refactor.
 * Sticky top navigation + language switcher + login CTA.
 */
import { useTranslation } from "react-i18next";
import { ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CompactLanguageSwitcher } from "@/components/CompactLanguageSwitcher";

export default function LandingHeader({ user, onEnter, onEmailAuth }) {
  const { t } = useTranslation();
  return (
    <header className="sticky top-0 inset-x-0 z-50 glass-panel">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-12 h-16 flex items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-12 w-12 object-contain" />
          <div>
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
        <div className="flex items-center gap-3">
          <CompactLanguageSwitcher testid="landing-lang-switcher" />
          <Button
            data-testid="header-login-btn"
            onClick={user ? onEnter : onEmailAuth}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none px-5 h-10"
          >
            {user ? t("landing.header.enterPanel") : t("landing.header.loginButton")}{" "}
            <ArrowUpRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </div>
    </header>
  );
}
