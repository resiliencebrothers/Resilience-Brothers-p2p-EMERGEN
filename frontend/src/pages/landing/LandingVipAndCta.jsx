/**
 * iter100 — Extracted from Landing.jsx.
 * VIP tier promo + final CTA + footer.
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function LandingVipAndCta({ onEnter, onEmailAuth }) {
  const { t } = useTranslation();
  const vipKpis = useMemo(() => [
    ["0%", t("landing.vipSection.kpiCommission")],
    ["+5", t("landing.vipSection.kpiRate")],
    [t("landing.vipSection.kpiCourierValue"), t("landing.vipSection.kpiCourier")],
    [t("landing.vipSection.kpiAccumulateValue"), t("landing.vipSection.kpiAccumulate")],
  ], [t]);

  return (
    <>
      <section id="vip" className="py-16 sm:py-20 border-t border-white/5 bg-[#0c0c0c]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-12 grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.vipSection.eyebrow")}</div>
            <h2 className="font-display text-3xl lg:text-5xl mb-6">{t("landing.vipSection.title")}</h2>
            <p className="text-neutral-400 mb-8 text-base leading-relaxed">
              {t("landing.vipSection.descriptionA")}{" "}
              <span className="text-white">{t("landing.vipSection.descriptionHighlight")}</span>{" "}
              {t("landing.vipSection.descriptionB")}
            </p>
            <div className="grid grid-cols-2 gap-3">
              {vipKpis.map(([v, l]) => (
                <div key={l} className="border border-white/10 p-4">
                  <div className="font-display text-2xl text-[#8B5CF6]">{v}</div>
                  <div className="micro-label text-neutral-500 mt-1">{l}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="relative">
            <div className="aspect-square bg-black flex items-center justify-center border border-[#8B5CF6]/20 overflow-hidden">
              <img
                src="/branding/logo-1200.png"
                alt="Resilience Brothers"
                className="w-4/5 h-4/5 object-contain"
              />
            </div>
            <div className="absolute bottom-0 left-0 right-0 p-6 glass-panel">
              <div className="micro-label text-[#8B5CF6] mb-2">{t("landing.vipSection.statusLabel")}</div>
              <p className="font-display text-xl">{t("landing.vipSection.statusTagline")}</p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-16 sm:py-24 border-t border-white/5">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 text-center">
          <h2 className="font-display text-3xl sm:text-4xl lg:text-6xl mb-6">
            {t("landing.cta.title")}
          </h2>
          <p className="text-neutral-400 mb-8 text-lg">{t("landing.cta.subtitle")}</p>
          <Button
            data-testid="cta-signup-btn"
            onClick={onEnter}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none px-10 h-14 text-base"
          >
            {t("landing.cta.googleButton")} <ArrowUpRight className="w-5 h-5 ml-1" />
          </Button>
          <div className="mt-4">
            <button
              data-testid="cta-email-link"
              onClick={onEmailAuth}
              className="text-sm text-neutral-400 hover:text-[#8B5CF6] underline underline-offset-4"
            >
              {t("landing.cta.emailLink")}
            </button>
          </div>
        </div>
      </section>

      <footer className="border-t border-white/5 py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-12 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-9 w-9 object-contain" />
            <span className="micro-label text-neutral-500">{t("landing.footer.copy")}</span>
          </div>
          <span className="micro-label text-neutral-600">{t("landing.footer.tagline")}</span>
        </div>
      </footer>
    </>
  );
}
