/**
 * iter100 — Extracted from Landing.jsx.
 * Services (crypto + marketplace) + step-by-step "cómo funciona".
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { BadgeCheck } from "lucide-react";

const MARKETPLACE_BG = "url(https://images.unsplash.com/photo-1493946740644-2d8a1f1a6aff?crop=entropy&cs=srgb&fm=jpg&q=85)";

export default function LandingServices({ scrollY }) {
  const { t } = useTranslation();
  const cryptoBullets = t("landing.services.cryptoBullets", { returnObjects: true }) || [];
  const marketplaceBullets = t("landing.services.marketplaceBullets", { returnObjects: true }) || [];
  const howSteps = t("landing.how.steps", { returnObjects: true }) || [];

  const marketplaceBg = useMemo(() => ({
    backgroundImage: MARKETPLACE_BG,
    transform: `translate3d(0, ${scrollY * 0.08}px, 0)`,
  }), [scrollY]);

  return (
    <>
      <section id="services" className="py-16 sm:py-20 border-t border-white/5 bg-[#0c0c0c]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-12">
          <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.services.eyebrow")}</div>
          <h2 className="font-display text-3xl lg:text-5xl mb-12 max-w-3xl">{t("landing.services.title")}</h2>
          <div className="grid lg:grid-cols-2 gap-6">
            <div className="tactile-card p-8 hover:glow-yellow transition-shadow">
              <div className="flex items-center justify-between mb-6">
                <span className="micro-label text-neutral-500">{t("landing.services.section01")}</span>
                <span className="text-xs font-mono text-[#22C55E]">{t("landing.services.active")}</span>
              </div>
              <h3 className="font-display text-3xl mb-4">{t("landing.services.cryptoTitle")}</h3>
              <p className="text-neutral-400 mb-6">{t("landing.services.cryptoDescription")}</p>
              <ul className="space-y-3 text-sm">
                {cryptoBullets.map((b) => (
                  <li key={b} className="flex items-center gap-3 text-neutral-300">
                    <BadgeCheck className="w-4 h-4 text-[#8B5CF6] shrink-0" />
                    {b}
                  </li>
                ))}
              </ul>
            </div>
            <div className="tactile-card p-8 hover:glow-yellow transition-shadow relative overflow-hidden">
              <div className="absolute inset-0 bg-cover bg-center opacity-20 will-change-transform" style={marketplaceBg}></div>
              <div className="relative">
                <div className="flex items-center justify-between mb-6">
                  <span className="micro-label text-neutral-500">{t("landing.services.section02")}</span>
                  <span className="text-xs font-mono text-[#8B5CF6]">{t("landing.services.vipOnly")}</span>
                </div>
                <h3 className="font-display text-3xl mb-4">{t("landing.services.marketplaceTitle")}</h3>
                <p className="text-neutral-400 mb-6">{t("landing.services.marketplaceDescription")}</p>
                <ul className="space-y-3 text-sm">
                  {marketplaceBullets.map((b) => (
                    <li key={b} className="flex items-center gap-3 text-neutral-300">
                      <BadgeCheck className="w-4 h-4 text-[#8B5CF6] shrink-0" />
                      {b}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="how" className="py-16 sm:py-20 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-12">
          <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.how.eyebrow")}</div>
          <h2 className="font-display text-3xl lg:text-5xl mb-12 max-w-3xl">{t("landing.how.title")}</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
            {howSteps.map((s) => (
              <div key={s.n} className="tactile-card p-6">
                <div className="font-display text-5xl text-[#8B5CF6]/30">{s.n}</div>
                <h3 className="font-display text-lg mt-4 mb-2">{s.t}</h3>
                <p className="text-neutral-400 text-sm">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
