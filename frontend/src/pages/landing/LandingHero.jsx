/**
 * iter100 — Extracted from Landing.jsx.
 * Hero section: parallax background image + H1 + description + CTAs + KPI grid.
 */
import { useMemo } from "react";
import { useTranslation, Trans } from "react-i18next";
import { ChevronRight, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ShareAppButton } from "@/components/ShareAppButton";
import { QrShareButton } from "@/components/QrShareButton";

const HERO_BG = "url(https://images.unsplash.com/photo-1644088379091-d574269d422f?crop=entropy&cs=srgb&fm=jpg&q=85)";

export default function LandingHero({ scrollY, onEnter, onEmailAuth }) {
  const { t } = useTranslation();

  const bgStyle = useMemo(() => ({
    backgroundImage: HERO_BG,
    transform: `translate3d(0, ${scrollY * 0.35}px, 0)`,
  }), [scrollY]);

  // Static, translation-driven KPI cards. Memoised so the array
  // identity is stable when the parent re-renders on scroll.
  const kpis = useMemo(() => ([
    { v: "+12",  l: t("landing.hero.kpiCountries") },
    { v: "VIP",  l: t("landing.hero.kpiVipRate") },
    { v: "24h",  l: t("landing.hero.kpiSettlement") },
    { v: "100%", l: t("landing.hero.kpiP2p") },
  ]), [t]);

  return (
    <section className="relative pt-24 sm:pt-32 pb-16 sm:pb-24 overflow-hidden">
      <div className="landing-hero-bg absolute inset-0 bg-cover bg-center opacity-55 will-change-transform" style={bgStyle}></div>
      <div className="landing-hero-overlay absolute inset-0 bg-gradient-to-b from-[#14101F]/20 via-[#14101F]/55 to-[#14101F]"></div>
      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-12 grid lg:grid-cols-12 gap-8 items-end">
        <div className="lg:col-span-8 fade-up">
          <div className="flex items-center gap-3 mb-4">
            <span className="brand-dot"></span>
            <span className="brand-divider flex-1 max-w-[80px] sm:max-w-[120px]"></span>
            <span className="brand-title text-[1.05rem] sm:text-xl md:text-2xl whitespace-nowrap" data-testid="landing-brand-title">
              Resilience Brothers
            </span>
            <span className="brand-divider flex-1 max-w-[80px] sm:max-w-[120px]"></span>
            <span className="brand-dot"></span>
          </div>
          <div className="flex items-center gap-3 mb-6">
            <span className="w-2 h-2 bg-[#22C55E] rounded-full pulse-dot"></span>
            <span className="micro-label text-neutral-400">{t("landing.hero.livePill")}</span>
          </div>
          <h1 className="font-display text-3xl sm:text-5xl lg:text-7xl leading-[1.05] sm:leading-[0.95] mb-6">
            {t("landing.hero.titleLine1")}<br />
            <span className="text-[#8B5CF6]">{t("landing.hero.titleAccent")}</span><br />
            {t("landing.hero.titleLine3")}
          </h1>
          <p className="text-neutral-300 text-base md:text-lg max-w-2xl leading-relaxed mb-8">
            {t("landing.hero.descriptionA")}
            <span className="text-white"> {t("landing.hero.descriptionHighlight")} </span>
            {t("landing.hero.descriptionB")}
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <Button
              data-testid="hero-start-btn"
              onClick={onEnter}
              className="inline-flex items-center justify-center bg-violet-600 hover:bg-violet-500 text-white font-medium text-base py-3 px-8 h-14 rounded-full transition-all duration-300 shadow-[0_4px_14px_0_rgba(139,92,246,0.39)] hover:shadow-[0_6px_20px_rgba(139,92,246,0.5)] hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#14101F]"
            >
              {t("landing.hero.startButton")} <ChevronRight className="w-5 h-5 ml-1" />
            </Button>
            <Button
              data-testid="hero-email-btn"
              onClick={onEmailAuth}
              variant="ghost"
              className="inline-flex items-center justify-center bg-transparent border border-white/15 hover:border-white/30 hover:bg-white/5 text-white font-medium text-sm py-3 px-8 h-14 rounded-full transition-all duration-300 hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:ring-offset-2 focus-visible:ring-offset-[#14101F]"
            >
              <Mail className="w-4 h-4 mr-2" /> {t("landing.hero.emailButton")}
            </Button>
            <ShareAppButton
              testid="hero-share-btn"
              url={typeof window !== "undefined" ? window.location.origin : ""}
              text={t("landing.shareText")}
              label={t("landing.shareApp")}
              variant="ghost"
              className="sm:hidden inline-flex items-center justify-center bg-transparent border border-white/15 hover:border-white/30 hover:bg-white/5 text-white font-medium text-sm py-3 px-6 h-14 rounded-full transition-all duration-300"
            />
            <QrShareButton
              testid="hero-qr-btn"
              url={typeof window !== "undefined" ? window.location.origin : ""}
              variant="ghost"
              className="sm:hidden inline-flex items-center justify-center bg-transparent border border-white/15 hover:border-white/30 hover:bg-white/5 text-white font-medium text-sm py-3 px-5 h-14 rounded-full transition-all duration-300"
            />
          </div>
          <p className="text-[0.7rem] text-neutral-500 mt-3 max-w-md">
            <Trans
              i18nKey="landing.hero.emailFallback"
              components={[
                <button
                  key="email-fallback-btn"
                  onClick={onEmailAuth}
                  className="text-[#8B5CF6] hover:underline"
                  data-testid="hero-email-link"
                />,
              ]}
            />
          </p>
        </div>
        <div className="lg:col-span-4 grid grid-cols-2 gap-4 mt-8 lg:mt-0">
          {kpis.map((s) => (
            <div key={s.l} className="tactile-card p-4">
              <div className="font-display text-2xl text-[#8B5CF6]">{s.v}</div>
              <div className="micro-label text-neutral-500 mt-2">{s.l}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
