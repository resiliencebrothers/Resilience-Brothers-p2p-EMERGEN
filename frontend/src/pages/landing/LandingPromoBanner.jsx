import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Megaphone, ArrowRight } from "lucide-react";

// iter227 — La "promo del mes" del póster QR (settings id=qr_poster) también
// se muestra como banner en la landing para atraer nuevos clientes.
// Si no hay promo configurada, el banner no se renderiza.
export default function LandingPromoBanner({ onEmailAuth }) {
  const { t } = useTranslation();
  const [promo, setPromo] = useState("");
  const [heading, setHeading] = useState("");

  useEffect(() => {
    axios.get(`${API}/qr-poster`)
      .then((r) => {
        setPromo((r.data?.promo || "").trim());
        setHeading((r.data?.heading || "").trim());
      })
      .catch(() => {});
  }, []);

  if (!promo) return null;

  return (
    <section className="relative z-10 px-4 sm:px-8" data-testid="landing-promo-banner">
      <div className="max-w-6xl mx-auto -mt-6 mb-10">
        <div className="border border-amber-400/40 bg-amber-400/[0.07] backdrop-blur-sm px-5 py-4 sm:px-8 sm:py-5 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-center gap-3 flex-shrink-0">
            <span className="w-10 h-10 flex items-center justify-center bg-amber-400/15 border border-amber-400/30">
              <Megaphone className="w-5 h-5 text-amber-300" />
            </span>
            <span className="micro-label text-amber-300 whitespace-nowrap">
              {t("landing.promoBanner.label")}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            {heading && (
              <div className="text-xs text-neutral-400 uppercase tracking-wider mb-0.5 truncate" data-testid="landing-promo-heading">
                {heading}
              </div>
            )}
            <p className="text-base md:text-lg text-white font-medium" data-testid="landing-promo-text">
              {promo}
            </p>
          </div>
          <button
            onClick={onEmailAuth}
            data-testid="landing-promo-cta"
            className="flex-shrink-0 inline-flex items-center gap-2 px-5 py-2.5 bg-amber-400 hover:bg-amber-300 text-[#14101F] text-sm font-bold uppercase tracking-wider transition-colors"
          >
            {t("landing.promoBanner.cta")}
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </section>
  );
}
