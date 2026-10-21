import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Carousel, CarouselContent, CarouselItem } from "@/components/ui/carousel";
import { Tag, BadgeCheck, ArrowRight, Package } from "lucide-react";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

function OfferCard({ p, onOpen }) {
  const { t } = useTranslation();
  return (
    <button
      data-testid={`offer-card-${p.id}`}
      onClick={() => onOpen(p.id)}
      className="tactile-card text-left overflow-hidden flex flex-col h-full w-full group hover:border-[#8B5CF6]/50 transition-colors"
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
  );
}

export default function OffersBanner() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [offers, setOffers] = useState([]);
  const [api, setApi] = useState(null);
  const [selected, setSelected] = useState(0);
  const [count, setCount] = useState(0);
  const [paused, setPaused] = useState(false);

  const load = useCallback(() => {
    axios.get(`${API}/products/offers`, { withCredentials: true })
      .then((r) => setOffers(Array.isArray(r.data) ? r.data : []))
      .catch(() => setOffers([]));
  }, []);

  useEffect(() => { load(); }, [load]);
  useLiveEvent("products_changed", load);

  // Estado del carrusel (para los puntos de navegación).
  useEffect(() => {
    if (!api) return;
    const sync = () => { setCount(api.scrollSnapList().length); setSelected(api.selectedScrollSnap()); };
    sync();
    api.on("select", sync);
    api.on("reInit", sync);
    return () => { api.off("select", sync); api.off("reInit", sync); };
  }, [api]);

  // Rotación automática (se pausa al pasar el ratón / interactuar).
  useEffect(() => {
    if (!api || offers.length <= 1 || paused) return;
    const id = setInterval(() => api.scrollNext(), 4500);
    return () => clearInterval(id);
  }, [api, offers.length, paused]);

  const open = (pid) => navigate(`/dashboard/marketplace?product=${pid}`);

  if (offers.length === 0) return null;

  return (
    <section data-testid="offers-banner" className="space-y-3"
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
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

      <Carousel setApi={setApi} opts={{ loop: offers.length > 1, align: "start" }} className="w-full">
        <CarouselContent className="-ml-4">
          {offers.map((p) => (
            <CarouselItem key={p.id} className="pl-4 basis-full sm:basis-1/2 lg:basis-1/3">
              <OfferCard p={p} onOpen={open} />
            </CarouselItem>
          ))}
        </CarouselContent>
      </Carousel>

      {count > 1 && (
        <div className="flex justify-center gap-1.5 pt-1" data-testid="offers-dots">
          {Array.from({ length: count }).map((_, i) => (
            <button
              key={i}
              aria-label={`Oferta ${i + 1}`}
              data-testid={`offers-dot-${i}`}
              onClick={() => api?.scrollTo(i)}
              className={`h-1.5 rounded-full transition-all ${i === selected ? "w-5 bg-[#8B5CF6]" : "w-1.5 bg-neutral-600 hover:bg-neutral-400"}`}
            />
          ))}
        </div>
      )}
    </section>
  );
}
