import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { MapPin, LoaderCircle, Truck } from "lucide-react";

// Prop. Tarifa-Municipio — "Ver cobertura de entrega": el comprador consulta,
// ANTES de llenar el carrito, qué provincias y municipios tienen mensajería y
// a qué precio. Solo lectura de las tarifas activas; una sola llamada agrupada
// por provincia en el cliente.
export default function DeliveryCoverageDialog() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [groups, setGroups] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/courier/municipality-rates`, { withCredentials: true });
      const by = {};
      (r.data || []).forEach((m) => {
        const p = m.province || "La Habana";
        (by[p] = by[p] || []).push(m);
      });
      Object.values(by).forEach((list) => list.sort((a, b) => a.municipality.localeCompare(b.municipality)));
      const ordered = Object.keys(by).sort((a, b) => a.localeCompare(b)).map((p) => ({ province: p, munis: by[p] }));
      setGroups(ordered);
    } catch {
      setGroups([]);
    } finally {
      setLoading(false);
    }
  };

  const onOpenChange = (v) => {
    setOpen(v);
    if (v && groups === null) load();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          data-testid="delivery-coverage-btn"
          className="rounded-none border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 h-10 text-xs whitespace-nowrap"
        >
          <Truck className="w-4 h-4 mr-1.5" /> {t("marketplace.coverageBtn")}
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto" data-testid="delivery-coverage-dialog">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <MapPin className="w-5 h-5 text-[#8B5CF6]" /> {t("marketplace.coverageTitle")}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-neutral-400">{t("marketplace.coverageIntro")}</p>

        {loading && (
          <div className="flex items-center gap-2 text-sm text-neutral-500 py-6" data-testid="coverage-loading">
            <LoaderCircle className="w-4 h-4 animate-spin" /> {t("marketplace.coverageLoading")}
          </div>
        )}

        {!loading && groups !== null && groups.length === 0 && (
          <p className="text-sm text-neutral-500 py-6 text-center" data-testid="coverage-empty">
            {t("marketplace.coverageEmpty")}
          </p>
        )}

        {!loading && groups && groups.length > 0 && (
          <div className="space-y-4" data-testid="coverage-list">
            {groups.map((g) => (
              <div key={g.province} className="border border-white/10 bg-[#0a0a0a]" data-testid={`coverage-province-${g.province}`}>
                <div className="px-3 py-2 border-b border-white/10 flex items-center justify-between">
                  <span className="font-display text-sm text-[#8B5CF6]">{g.province}</span>
                  <span className="text-[0.65rem] text-neutral-500">{t("marketplace.coverageMuniCount", { count: g.munis.length })}</span>
                </div>
                <ul className="divide-y divide-white/5">
                  {g.munis.map((m) => (
                    <li key={m.id} className="px-3 py-2 flex items-center justify-between text-sm" data-testid={`coverage-muni-${m.id}`}>
                      <span className="text-neutral-200">{m.municipality}</span>
                      <span className="font-mono text-[#8B5CF6]">{m.price_usdt} USDT</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        <p className="text-[0.7rem] text-amber-300/90 border border-amber-400/20 bg-amber-400/5 px-3 py-2 mt-2" data-testid="coverage-pickup-note">
          {t("marketplace.coveragePickupNote")}
        </p>
      </DialogContent>
    </Dialog>
  );
}
