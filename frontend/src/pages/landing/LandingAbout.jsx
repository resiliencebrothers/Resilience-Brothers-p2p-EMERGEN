/**
 * iter100 — Extracted from Landing.jsx.
 * "Sobre nosotros" tetris-grid section (5 mixed-size cards).
 */
import { useTranslation } from "react-i18next";
import { Globe2, ShieldCheck, Zap, Activity, Boxes } from "lucide-react";

export default function LandingAbout() {
  const { t } = useTranslation();
  return (
    <section id="about" className="py-16 sm:py-20 border-t border-white/5">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-12">
        <div className="flex items-start justify-between mb-12 flex-wrap gap-4">
          <div>
            <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.about.eyebrow")}</div>
            <h2 className="font-display text-3xl lg:text-5xl max-w-2xl">{t("landing.about.title")}</h2>
          </div>
          <p className="text-neutral-400 max-w-md text-sm md:text-base leading-relaxed">
            {t("landing.about.description")}
          </p>
        </div>
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 lg:col-span-7 tactile-card p-8 relative overflow-hidden min-h-[280px] grain-overlay">
            <Globe2 className="w-10 h-10 text-[#8B5CF6] mb-6" />
            <h3 className="font-display text-2xl mb-3">{t("landing.about.globalTitle")}</h3>
            <p className="text-neutral-400 max-w-md">
              {t("landing.about.globalDescription")}
            </p>
          </div>
          <div className="col-span-6 lg:col-span-5 tactile-card p-6 min-h-[280px] flex flex-col justify-between">
            <ShieldCheck className="w-10 h-10 text-[#8B5CF6]" />
            <div>
              <h3 className="font-display text-xl mb-2">{t("landing.about.proofsTitle")}</h3>
              <p className="text-neutral-400 text-sm">{t("landing.about.proofsDescription")}</p>
            </div>
          </div>
          <div className="col-span-6 lg:col-span-4 tactile-card p-6 min-h-[220px]">
            <Zap className="w-9 h-9 text-[#8B5CF6] mb-4" />
            <h3 className="font-display text-xl mb-2">{t("landing.about.settlementTitle")}</h3>
            <p className="text-neutral-400 text-sm">{t("landing.about.settlementDescription")}</p>
          </div>
          <div className="col-span-12 lg:col-span-4 tactile-card p-6 min-h-[220px]">
            <Activity className="w-9 h-9 text-[#8B5CF6] mb-4" />
            <h3 className="font-display text-xl mb-2">{t("landing.about.dynamicRatesTitle")}</h3>
            <p className="text-neutral-400 text-sm">{t("landing.about.dynamicRatesDescription")}</p>
          </div>
          <div className="col-span-12 lg:col-span-4 tactile-card p-6 min-h-[220px]">
            <Boxes className="w-9 h-9 text-[#8B5CF6] mb-4" />
            <h3 className="font-display text-xl mb-2">{t("landing.about.goodsTitle")}</h3>
            <p className="text-neutral-400 text-sm">{t("landing.about.goodsDescription")}</p>
          </div>
        </div>
      </div>
    </section>
  );
}
