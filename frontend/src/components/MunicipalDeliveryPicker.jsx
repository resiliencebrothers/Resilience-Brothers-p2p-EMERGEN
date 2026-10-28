import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@/components/ui/select";
import { LoaderCircle, LocateFixed, Check } from "lucide-react";

const NOT_LISTED = "__not_listed__";

// Prop. Tarifa-Municipio — selector municipio-first para compras con entrega a
// domicilio. El municipio elegido determina la tarifa fija (la fuente de precio
// es el backend); el mapa/GPS es OPCIONAL y solo sirve de referencia para el
// mensajero. Nunca bloquea la compra por no poder geolocalizar la dirección.
export default function MunicipalDeliveryPicker({
  currency = "USDT", amount, onQuote, onCoords, onMunicipality, onNoCoverage,
  suppressNoCoverageNote = false,
}) {
  const { t } = useTranslation();
  const [provinces, setProvinces] = useState(null);
  const [province, setProvince] = useState("");
  const [munis, setMunis] = useState(null);
  const [muniId, setMuniId] = useState("");
  const [quoting, setQuoting] = useState(false);
  const [quote, setQuote] = useState(null);
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState("");
  const [coordsOk, setCoordsOk] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const r = await axios.get(`${API}/courier/delivery-provinces`, { withCredentials: true });
        if (!active) return;
        const list = r.data || [];
        setProvinces(list);
        if (list.length === 1) setProvince(list[0]);
      } catch {
        if (active) setProvinces([]);
      }
    })();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!province) { setMunis(null); return; }
    let active = true;
    setMuniId(""); setQuote(null);
    if (onQuote) onQuote(null);
    if (onMunicipality) onMunicipality(null);
    if (onNoCoverage) onNoCoverage(false);
    (async () => {
      try {
        const r = await axios.get(`${API}/courier/municipality-rates`, {
          params: { province }, withCredentials: true,
        });
        if (active) setMunis(r.data || []);
      } catch {
        if (active) setMunis([]);
      }
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [province]);

  useEffect(() => {
    if (!muniId || muniId === NOT_LISTED) return;
    let active = true;
    setQuoting(true);
    (async () => {
      try {
        const r = await axios.get(`${API}/vip/courier-municipality-quote`, {
          params: { municipality: muniId, province, currency, amount: amount || 0 },
          withCredentials: true,
        });
        if (!active) return;
        if (r.data?.matched && (r.data.free || Number(r.data.fee_usdt) > 0 || r.data.enabled === false)) {
          setQuote(r.data);
          if (onQuote) onQuote(r.data);
          if (onNoCoverage) onNoCoverage(false);
          const m = (munis || []).find((x) => x.id === muniId);
          if (onMunicipality) {
            onMunicipality({ id: muniId, name: r.data.municipality || m?.municipality, province });
          }
        } else {
          setQuote(null);
          if (onQuote) onQuote(null);
          if (onMunicipality) onMunicipality(null);
          if (onNoCoverage) onNoCoverage(true);
        }
      } catch {
        if (!active) return;
        setQuote(null);
        if (onQuote) onQuote(null);
      } finally {
        if (active) setQuoting(false);
      }
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [muniId, amount]);

  const onMuniChange = (val) => {
    setMuniId(val);
    if (val === NOT_LISTED) {
      setQuote(null);
      if (onQuote) onQuote(null);
      if (onMunicipality) onMunicipality(null);
      if (onNoCoverage) onNoCoverage(true);
    }
  };

  const shareLocation = () => {
    setGeoError("");
    if (!navigator.geolocation) { setGeoError(t("courier.geoUnsupported")); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false); setCoordsOk(true);
        if (onCoords) onCoords({ lat: pos.coords.latitude, lon: pos.coords.longitude });
      },
      () => { setLocating(false); setGeoError(t("courier.geoDenied")); },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 },
    );
  };

  const noCoverage = muniId === NOT_LISTED || (!!muniId && !quoting && !quote);
  const emptyProvince = !!province && munis !== null && munis.length === 0;

  return (
    <div className="space-y-3" data-testid="municipal-delivery-picker">
      {provinces !== null && provinces.length > 1 && (
        <div>
          <Label className="micro-label text-neutral-500">{t("municipalDelivery.provinceLabel")}</Label>
          <Select value={province} onValueChange={setProvince}>
            <SelectTrigger data-testid="delivery-province-select" className="h-11 rounded-none mt-2 bg-[#0a0a0a] border-white/10 text-sm">
              <SelectValue placeholder={t("municipalDelivery.provincePlaceholder")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
              {provinces.map((p) => (<SelectItem key={p} value={p}>{p}</SelectItem>))}
            </SelectContent>
          </Select>
        </div>
      )}

      <div>
        <Label className="micro-label text-neutral-500">{t("municipalDelivery.muniLabel")}</Label>
        <Select value={muniId} onValueChange={onMuniChange} disabled={!province}>
          <SelectTrigger data-testid="delivery-municipality-select" className="h-11 rounded-none mt-2 bg-[#0a0a0a] border-[#8B5CF6]/40 text-sm">
            <SelectValue placeholder={province ? t("municipalDelivery.muniPlaceholder") : t("municipalDelivery.pickProvinceFirst")} />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
            {(munis || []).map((m) => (
              <SelectItem key={m.id} value={m.id} data-testid={`delivery-muni-opt-${m.id}`}>
                {m.municipality} — {m.price_usdt} USDT
              </SelectItem>
            ))}
            <SelectItem value={NOT_LISTED} data-testid="delivery-muni-not-listed">
              {t("municipalDelivery.notListed")}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      {quoting && (
        <p className="text-[0.7rem] text-neutral-500" data-testid="delivery-quote-loading">
          {t("courier.quoting")}
        </p>
      )}

      {quote && !quoting && (
        (quote.free || quote.enabled === false) ? (
          <p className="text-[0.7rem] text-[#22C55E] border border-[#22C55E]/30 bg-[#22C55E]/5 px-3 py-2" data-testid="delivery-quote-free">
            {quote.free ? t("courier.freeQuote", { min: quote.free_min_usdt }) : t("municipalDelivery.noChargeNote")}
          </p>
        ) : (
          <div className="text-[0.7rem] text-neutral-300 border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 px-3 py-2 space-y-0.5" data-testid="delivery-quote-result">
            <div className="flex justify-between">
              <span className="text-neutral-500">{t("courier.municipality")}</span>
              <span className="font-mono">{quote.municipality}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">{t("courier.cost")}</span>
              <span className="font-mono text-[#8B5CF6]">{quote.fee_usdt} USDT</span>
            </div>
            <p className="text-[0.65rem] text-amber-400/90 pt-0.5">{t("municipalDelivery.fixedNote")}</p>
          </div>
        )
      )}

      {(((!suppressNoCoverageNote && noCoverage) || emptyProvince)) && !quoting && (
        <p className="text-[0.72rem] text-amber-300 border border-amber-400/30 bg-amber-400/5 px-3 py-2" data-testid="delivery-no-coverage">
          {t("municipalDelivery.noCoverage")}
        </p>
      )}

      {!noCoverage && (
      <div>
        <Button
          type="button"
          variant="outline"
          onClick={shareLocation}
          disabled={locating}
          data-testid="delivery-share-location-btn"
          className="rounded-none border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 h-9 text-xs"
        >
          {locating
            ? <LoaderCircle className="w-3.5 h-3.5 animate-spin mr-1.5" />
            : coordsOk
              ? <Check className="w-3.5 h-3.5 mr-1.5" />
              : <LocateFixed className="w-3.5 h-3.5 mr-1.5" />}
          {coordsOk ? t("municipalDelivery.locationShared") : t("municipalDelivery.shareLocationOptional")}
        </Button>
        {geoError && <p className="text-[0.7rem] text-amber-400 mt-1" data-testid="delivery-geo-error">{geoError}</p>}
        <p className="text-[0.62rem] text-neutral-500 mt-1">{t("municipalDelivery.gpsHint")}</p>
      </div>
      )}
    </div>
  );
}
