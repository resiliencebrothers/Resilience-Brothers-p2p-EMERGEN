import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Wrench, Search, MapPin, Clock, BadgeCheck, CalendarClock, CreditCard } from "lucide-react";
import { toast } from "sonner";

// Pestaña SERVICIOS del mercado (cliente). Muestra los servicios publicados por
// las Empresas con búsqueda, filtro por categoría y modalidad, y una ficha de
// detalle con disponibilidad y condiciones de pago. La reserva y el cobro en
// línea llegan en la próxima fase (CTA informativo por ahora).
const WD = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MODALITY = { local: "En el local", domicilio: "A domicilio", remoto: "Remoto / Online", alquiler: "Alquiler" };
const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

const priceText = (s) => {
  if (s.pricing_type === "quote") return "A presupuestar";
  const unit = { hourly: "/hora", daily: "/día", per_person: "/persona" }[s.pricing_type] || "";
  return `${s.price_usdt} USDT${unit}`;
};

const depositText = (s) => {
  if (!s.deposit_type || s.deposit_type === "none" || !s.deposit_value) return null;
  return s.deposit_type === "percent"
    ? `Anticipo del ${s.deposit_value}%`
    : `Anticipo de ${s.deposit_value} USDT`;
};

export default function ServicesMarketplace() {
  const [services, setServices] = useState([]);
  const [categories, setCategories] = useState([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [modality, setModality] = useState("");
  const [detail, setDetail] = useState(null);

  const load = useCallback(() => {
    axios.get(`${API}/services`, { withCredentials: true })
      .then((r) => setServices(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/service-categories`, { withCredentials: true })
      .then((r) => setCategories(r.data)).catch(() => {});
  }, [load]);

  // Un servicio recién aprobado/pausado/editado aparece sin recargar la página.
  useLiveEvent("services_changed", load);

  const catName = (slug) => categories.find((c) => c.slug === slug)?.name || slug;
  const usedCategories = useMemo(
    () => categories.filter((c) => services.some((s) => s.category === c.slug)),
    [categories, services]);

  const visible = services.filter((s) =>
    (!category || s.category === category) &&
    (!modality || s.modality === modality) &&
    (!query.trim() || norm(s.title).includes(norm(query)) ||
      norm(s.description).includes(norm(query)) || norm(s.coverage_zone).includes(norm(query))));

  return (
    <div className="space-y-6" data-testid="services-marketplace">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">Empresas de servicios</div>
        <h2 className="font-display text-2xl flex items-center gap-3">
          <Wrench className="w-6 h-6 text-[#8B5CF6]" /> Servicios
        </h2>
        <p className="text-sm text-neutral-400 mt-1">
          Explora barbería, limpieza, alquiler, asesoría y más de empresas verificadas. La reserva y el pago en línea llegan muy pronto.
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative w-full sm:w-[340px]">
          <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <Input data-testid="services-search-input" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar servicios, zona…" className="rounded-none pl-9 bg-[#0a0a0a] border-white/10 h-10" />
        </div>
      </div>

      {usedCategories.length > 0 && (
        <div className="flex gap-2 flex-wrap" data-testid="services-category-chips">
          <button data-testid="services-chip-all" onClick={() => setCategory("")}
            className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors ${!category ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
            Todas
          </button>
          {usedCategories.map((c) => (
            <button key={c.slug} data-testid={`services-chip-${c.slug}`} onClick={() => setCategory(category === c.slug ? "" : c.slug)}
              className={`px-3 py-1.5 text-xs uppercase tracking-wider border rounded-full transition-colors ${category === c.slug ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
              {c.name}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2 flex-wrap" data-testid="services-modality-chips">
        {["", "local", "domicilio", "remoto", "alquiler"].map((m) => (
          <button key={m || "all"} data-testid={`services-modality-${m || "all"}`} onClick={() => setModality(m)}
            className={`px-3 py-1 text-[0.7rem] uppercase tracking-wider border transition-colors ${modality === m ? "border-sky-400 text-sky-300 bg-sky-500/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
            {m ? MODALITY[m] : "Todas las modalidades"}
          </button>
        ))}
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {services.length === 0 && (
          <p className="text-neutral-500 col-span-full text-center py-12" data-testid="services-empty">
            Aún no hay servicios publicados. Vuelve pronto.
          </p>
        )}
        {services.length > 0 && visible.length === 0 && (
          <p className="text-neutral-500 col-span-full text-center py-12" data-testid="services-search-empty">
            No encontramos servicios con esos filtros.
          </p>
        )}
        {visible.map((s) => (
          <button key={s.id} onClick={() => setDetail(s)} data-testid={`service-card-${s.id}`}
            className="tactile-card overflow-hidden flex flex-col text-left hover:border-[#8B5CF6]/40 transition-colors">
            <div className="aspect-video bg-[#0a0a0a] overflow-hidden">
              {s.images?.[0] ? (
                <img src={s.images[0]} alt={s.title} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center"><Wrench className="w-10 h-10 text-neutral-700" /></div>
              )}
            </div>
            <div className="p-4 flex-1 flex flex-col">
              <div className="flex items-center justify-between gap-2">
                <div className="micro-label text-neutral-500">{catName(s.category)}</div>
                {s.owner_verified && (
                  <span data-testid={`service-verified-${s.id}`} title="Empresa verificada" className="inline-flex items-center gap-1 text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border border-emerald-500/40 bg-emerald-500/10 text-emerald-300">
                    <BadgeCheck className="w-3 h-3" /> Verificada
                  </span>
                )}
              </div>
              <h3 className="font-display text-lg mt-1">{s.title}</h3>
              <div className="text-xs text-neutral-400 mt-1">{s.owner_name}</div>
              <div className="text-xs text-neutral-500 mt-1 flex items-center gap-1">
                <MapPin className="w-3 h-3" /> {MODALITY[s.modality]}{s.coverage_zone ? ` · ${s.coverage_zone}` : ""}
              </div>
              <div className="mt-auto pt-3 font-display text-lg text-[#8B5CF6]">{priceText(s)}</div>
            </div>
          </button>
        ))}
      </div>

      <Dialog open={!!detail} onOpenChange={(v) => !v && setDetail(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[88vh] overflow-y-auto sm:max-w-xl" data-testid="service-detail-dialog">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="font-display flex items-center gap-2">
                  {detail.title}
                  {detail.owner_verified && <BadgeCheck className="w-5 h-5 text-emerald-400" />}
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                {detail.images?.[0] && (
                  <img src={detail.images[0]} alt={detail.title} className="w-full aspect-video object-cover border border-white/10" />
                )}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="text-sm text-neutral-400">{catName(detail.category)} · {MODALITY[detail.modality]}</div>
                  <div className="font-display text-2xl text-[#8B5CF6]" data-testid="service-detail-price">{priceText(detail)}</div>
                </div>
                <div className="text-sm text-neutral-300">Por <span className="text-neutral-100">{detail.owner_name}</span>{detail.coverage_zone ? ` · ${detail.coverage_zone}` : ""}</div>
                {detail.description && <p className="text-sm text-neutral-300 whitespace-pre-line">{detail.description}</p>}

                <div className="grid sm:grid-cols-2 gap-3">
                  <div className="border border-white/10 p-3">
                    <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> Detalles</div>
                    <ul className="text-sm text-neutral-300 space-y-1">
                      {detail.duration_minutes > 0 && <li>Duración: {detail.duration_minutes} min</li>}
                      {detail.capacity > 1 && <li>Cupos por turno: {detail.capacity}</li>}
                      {detail.min_notice_hours > 0 && <li>Aviso mínimo: {detail.min_notice_hours} h</li>}
                      {depositText(detail) && <li>{depositText(detail)}</li>}
                    </ul>
                  </div>
                  <div className="border border-white/10 p-3">
                    <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><CreditCard className="w-3.5 h-3.5" /> Pago</div>
                    <div className="text-sm text-neutral-300">
                      {(detail.payment_methods || []).map((m) => (m === "balance" ? "Saldo USDT" : "Efectivo")).join(" · ") || "Saldo USDT"}
                    </div>
                  </div>
                </div>

                {(detail.availability?.length > 0) && (
                  <div className="border border-white/10 p-3" data-testid="service-detail-availability">
                    <div className="micro-label text-[#8B5CF6] mb-2 flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" /> Horario habitual</div>
                    <ul className="text-sm text-neutral-300 space-y-1">
                      {detail.availability.map((w, i) => (
                        <li key={i}>{WD[w.day]}: {w.start}–{w.end}</li>
                      ))}
                    </ul>
                    {detail.timezone && (
                      <div className="text-xs text-neutral-500 mt-2" data-testid="service-detail-timezone">Zona horaria: {detail.timezone}</div>
                    )}
                    <div className="text-xs text-neutral-500 mt-1">Horario de atención orientativo; los turnos reservables se habilitarán en la próxima fase.</div>
                  </div>
                )}

                {detail.inclusions && (
                  <div><div className="micro-label text-neutral-500 mb-1">Incluye</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.inclusions}</p></div>
                )}
                {detail.exclusions && (
                  <div data-testid="service-detail-exclusions"><div className="micro-label text-neutral-500 mb-1">No incluye</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.exclusions}</p></div>
                )}
                {detail.requirements && (
                  <div><div className="micro-label text-neutral-500 mb-1">Requisitos</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.requirements}</p></div>
                )}
                {detail.cancellation_policy && (
                  <div><div className="micro-label text-neutral-500 mb-1">Cancelación</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.cancellation_policy}</p></div>
                )}

                <div className="border-l-4 border-amber-400 bg-amber-500/5 px-4 py-3 text-sm text-neutral-300" data-testid="service-detail-soon">
                  Reserva y pago en línea: <span className="text-amber-300">próximamente</span>. Por ahora puedes conocer la oferta; pronto podrás reservar turno y pagar desde aquí.
                </div>
                <Button data-testid="service-detail-book" onClick={() => toast("Las reservas en línea llegan en la próxima fase.")}
                  className="w-full bg-[#8B5CF6]/40 hover:bg-[#8B5CF6]/50 text-white font-semibold rounded-none h-11 cursor-not-allowed" disabled>
                  Reservar (próximamente)
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
