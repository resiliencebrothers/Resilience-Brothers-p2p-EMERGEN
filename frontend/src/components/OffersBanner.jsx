import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Tag, BadgeCheck, ArrowRight, Package } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function OffersBanner() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [offers, setOffers] = useState([]);

  const load = useCallback(() => {
    axios.get(`${API}/products/offers`, { withCredentials: true })
      .then((r) => setOffers(Array.isArray(r.data) ? r.data : []))
      .catch(() => setOffers([]));
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("products_changed", load);

  if (offers.length === 0) return null;

  return (
    <section data-testid="offers-banner" className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <h2 className="font-display text-lg flex items-center gap-2">
          <Tag className="w-5 h-5 text-[#8B5CF6]" /> {t("offers.title")}
        </h2>
        <button
          data-testid="offers-see-all"
          onClick={() => navigate("/dashboard/marketplace?offers=1")}
          className="micro-label text-[#8B5CF6] hover:underline flex items-center gap-1"
        >
          {t("offers.seeAll")} <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex gap-4 overflow-x-auto pb-2 snap-x sm:grid sm:grid-cols-2 lg:grid-cols-3 sm:overflow-visible">
        {offers.map((p) => (
          <button
            key={p.id}
            data-testid={`offer-card-${p.id}`}
            onClick={() => navigate(`/dashboard/marketplace?product=${p.id}`)}
            className="tactile-card text-left overflow-hidden flex flex-col min-w-[240px] sm:min-w-0 snap-start group hover:border-[#8B5CF6]/50 transition-colors"
          >
            <div className="relative aspect-video bg-[#0a0a0a] overflow-hidden">
              {p.image_url ? (
                <img src={p.image_url} alt={p.name}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <Package className="w-10 h-10 text-neutral-700" />
                </div>
              )}
              {p.offer_discount_pct > 0 && (
                <span data-testid={`offer-badge-${p.id}`}
                  className="absolute top-2 left-2 bg-[#EF4444] text-white text-xs font-bold px-2 py-0.5">
                  -{Number(p.offer_discount_pct).toFixed(0)}%
                </span>
              )}
            </div>
            <div className="p-3 flex-1 flex flex-col">
              <h3 className="font-display text-base leading-tight line-clamp-1">{p.name}</h3>
              <div className="text-xs text-neutral-500 flex items-center gap-1 mt-0.5 line-clamp-1">
                {p.owner_name || "Empresa"}
                {p.owner_verified && <BadgeCheck className="w-3.5 h-3.5 text-[#22C55E] shrink-0" />}
              </div>
              <div className="mt-auto pt-2 flex items-end gap-2">
                <span className="font-display text-lg text-[#8B5CF6]" data-testid={`offer-price-${p.id}`}>
                  {fmt(p.price_usdt)} <span className="text-[0.65rem] text-neutral-500">USDT</span>
                </span>
                {p.offer_original_price_usdt > 0 && (
                  <span className="text-xs text-neutral-500 line-through mb-1">
                    {fmt(p.offer_original_price_usdt)}
                  </span>
                )}
              </div>
              <span className="mt-2 text-xs text-[#8B5CF6] flex items-center gap-1 group-hover:gap-1.5 transition-all">
                {t("offers.view")} <ArrowRight className="w-3.5 h-3.5" />
              </span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
