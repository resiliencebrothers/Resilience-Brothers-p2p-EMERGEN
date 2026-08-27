import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { MapPin, LoaderCircle, LocateFixed } from "lucide-react";

// iter198 — shared courier quote widget (cash withdrawals + marketplace).
// The client types their address, we geocode it (OSM Nominatim), they pick
// the right match and we quote the road distance from the office (OSRM).
// The backend is the pricing authority; this is only a preview.
export default function CourierQuotePicker({ currency, amount, addressText, province, onCoords, onQuote }) {
  const { t } = useTranslation();
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [quote, setQuote] = useState(null);
  const [quoting, setQuoting] = useState(false);
  const [picked, setPicked] = useState(null);
  const [approx, setApprox] = useState(false);
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState("");
  // iter212 — selector de municipio cuando ni el mapa ni el texto lo detectan.
  const [munis, setMunis] = useState(null);
  const [showMuniPicker, setShowMuniPicker] = useState(false);
  const [muniPick, setMuniPick] = useState("");

  const openMuniPicker = async () => {
    setShowMuniPicker(true);
    if (munis === null) {
      try {
        const r = await axios.get(`${API}/courier/municipality-rates`, { withCredentials: true });
        setMunis(r.data || []);
      } catch {
        setMunis([]);
      }
    }
  };

  const pickMunicipality = async (name) => {
    setMuniPick(name);
    try {
      const r = await axios.get(`${API}/vip/courier-municipality-quote`, {
        params: { municipality: name, currency, amount: amount || 0 },
        withCredentials: true,
      });
      if (r.data?.matched) {
        setQuote(r.data);
        if (onQuote) onQuote(r.data);
      }
    } catch { /* se mantiene revisión manual */ }
  };

  // iter206 — el cliente comparte su ubicación GPS para cotizar y para que
  // el mensajero llegue al punto exacto.
  const useMyLocation = () => {
    setGeoError("");
    if (!navigator.geolocation) {
      setGeoError(t("courier.geoUnsupported"));
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude: lat, longitude: lon } = pos.coords;
        let name = t("courier.myLocation");
        try {
          const r = await axios.get(`${API}/vip/geo-reverse`, {
            params: { lat, lon }, withCredentials: true,
          });
          if (r.data?.display_name) name = `${t("courier.myLocation")} — ${r.data.display_name}`;
        } catch { /* la dirección legible es opcional */ }
        setResults(null);
        setApprox(false);
        setLocating(false);
        await pick({ lat, lon, display_name: name });
      },
      () => {
        setLocating(false);
        setGeoError(t("courier.geoDenied"));
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
    );
  };

  // iter211 — tarifa fija por municipio cuando el mapa no ubica la dirección.
  const tryMunicipality = async () => {
    try {
      const r = await axios.get(`${API}/vip/courier-municipality-quote`, {
        params: {
          address: `${addressText || ""} ${province || ""}`,
          currency, amount: amount || 0,
        },
        withCredentials: true,
      });
      if (r.data?.matched && (r.data.fee_usdt > 0 || r.data.free)) {
        setQuote(r.data);
        if (onQuote) onQuote(r.data);
        return true;
      }
    } catch { /* sin coincidencia → revisión manual */ }
    return false;
  };

  const search = async () => {
    if (!addressText || addressText.trim().length < 3) return;
    setSearching(true); setQuote(null); setPicked(null); setApprox(false);
    setShowMuniPicker(false); setMuniPick("");
    if (onQuote) onQuote(null);
    try {
      const r = await axios.get(`${API}/vip/geo-search`, {
        params: { q: addressText.trim(), province: province || "" }, withCredentials: true,
      });
      const list = r.data.results || [];
      setApprox(!!r.data.approximate);
      if (list.length === 0) {
        // iter211 — dirección no encontrada: probar tarifa fija por municipio
        // antes de caer en revisión manual.
        const ok = await tryMunicipality();
        if (ok) {
          setResults(null);
          setSearching(false);
          return;
        }
        // iter212 — sin municipio en el texto: dejar que el cliente lo elija.
        await openMuniPicker();
        if (onQuote) onQuote({ requires_manual_review: true, no_results: true });
      }
      if (list.length === 1) {
        // iter203 — una sola coincidencia: cotizar de inmediato,
        // sin exigir un toque extra sobre la dirección.
        setResults(null);
        setSearching(false);
        await pick(list[0]);
        return;
      }
      setResults(list);
    } catch {
      setResults([]);
      const ok = await tryMunicipality();
      if (!ok) {
        await openMuniPicker();
        if (onQuote) onQuote({ requires_manual_review: true, geo_error: true });
      }
    } finally {
      setSearching(false);
    }
  };

  const pick = async (res) => {
    setPicked(res); setResults(null); setQuoting(true);
    if (onCoords) onCoords({ lat: res.lat, lon: res.lon });
    try {
      const r = await axios.get(`${API}/vip/courier-route-quote`, {
        params: { lat: res.lat, lon: res.lon, currency, amount: amount || 0 },
        withCredentials: true,
      });
      if (r.data?.requires_manual_review) {
        // iter211 — ruta no calculable: probar tarifa fija por municipio.
        const ok = await tryMunicipality();
        if (!ok) {
          await openMuniPicker();
          setQuote(r.data);
          if (onQuote) onQuote(r.data);
        }
      } else {
        setQuote(r.data);
        if (onQuote) onQuote(r.data);
      }
    } catch {
      const ok = await tryMunicipality();
      if (!ok) {
        await openMuniPicker();
        const fallback = { requires_manual_review: true };
        setQuote(fallback);
        if (onQuote) onQuote(fallback);
      }
    } finally {
      setQuoting(false);
    }
  };

  return (
    <div className="space-y-2" data-testid="courier-quote-picker">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={search}
          disabled={searching || locating || !addressText || addressText.trim().length < 3}
          data-testid="courier-quote-calc-btn"
          className="rounded-none border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 h-9 text-xs"
        >
          {searching
            ? <LoaderCircle className="w-3.5 h-3.5 animate-spin mr-1.5" />
            : <MapPin className="w-3.5 h-3.5 mr-1.5" />}
          {t("courier.calcBtn")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={useMyLocation}
          disabled={locating || searching}
          data-testid="courier-share-location-btn"
          className="rounded-none border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 h-9 text-xs"
        >
          {locating
            ? <LoaderCircle className="w-3.5 h-3.5 animate-spin mr-1.5" />
            : <LocateFixed className="w-3.5 h-3.5 mr-1.5" />}
          {t("courier.shareLocationBtn")}
        </Button>
      </div>
      {geoError && (
        <p className="text-[0.7rem] text-amber-400" data-testid="courier-geo-error">{geoError}</p>
      )}

      {results !== null && results.length === 0 && (
        <p className="text-[0.7rem] text-amber-400" data-testid="courier-no-results">
          {t("courier.noResults")}
        </p>
      )}
      {results && results.length > 0 && (
        <div className="border border-white/10 divide-y divide-white/5" data-testid="courier-results">
          <p className="text-[0.65rem] text-neutral-500 px-3 py-2">{t("courier.pickAddress")}</p>
          {results.map((res, i) => (
            <button
              key={`${res.lat}-${res.lon}`}
              type="button"
              onClick={() => pick(res)}
              data-testid={`courier-result-${i}`}
              className="block w-full text-left px-3 py-2 text-xs text-neutral-300 hover:bg-[#8B5CF6]/10 transition-colors"
            >
              {res.display_name}
            </button>
          ))}
        </div>
      )}

      {approx && (results?.length > 0 || picked) && (
        <p className="text-[0.65rem] text-amber-400/90" data-testid="courier-approx-note">
          {t("courier.approxNote")}
        </p>
      )}

      {quoting && <p className="text-[0.7rem] text-neutral-500">{t("courier.quoting")}</p>}

      {quote && !quoting && (
        quote.free ? (
          <p
            className="text-[0.7rem] text-[#22C55E] border border-[#22C55E]/30 bg-[#22C55E]/5 px-3 py-2"
            data-testid="courier-quote-free"
          >
            {t("courier.freeQuote", { min: quote.free_min_usdt })}
          </p>
        ) : quote.requires_manual_review ? (
          <p
            className="text-[0.7rem] text-amber-400 border border-amber-400/30 bg-amber-400/5 px-3 py-2"
            data-testid="courier-quote-manual"
          >
            {t("courier.manualReview")}
          </p>
        ) : (
          <div
            className="text-[0.7rem] text-neutral-300 border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 px-3 py-2 space-y-0.5"
            data-testid="courier-quote-result"
          >
            {quote.municipality ? (
              <div className="flex justify-between" data-testid="courier-quote-municipality">
                <span className="text-neutral-500">{t("courier.municipality")}</span>
                <span className="font-mono">{quote.municipality}</span>
              </div>
            ) : (
              <div className="flex justify-between">
                <span className="text-neutral-500">{t("courier.distance")}</span>
                <span className="font-mono">{quote.km} km</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-neutral-500">{t("courier.cost")}</span>
              <span className="font-mono text-[#8B5CF6]">
                {quote.fee_usdt} USDT
                {quote.currency !== "USDT" ? ` ≈ ${quote.fee_currency_amount} ${quote.currency}` : ""}
              </span>
            </div>
            {quote.municipality && (
              <p className="text-[0.65rem] text-amber-400/90 pt-0.5" data-testid="courier-muni-note">
                {t("courier.muniFixedNote")}
              </p>
            )}
            <p className="text-[0.65rem] text-neutral-500 pt-1">{t("courier.deductNote")}</p>
          </div>
        )
      )}

      {/* iter212 — selector de municipio (mapa y texto no lo detectaron) */}
      {showMuniPicker && (
        <div className="space-y-1.5" data-testid="courier-muni-picker">
          <p className="text-[0.7rem] text-[#A78BFA]">{t("courier.muniPickLabel")}</p>
          <Select value={muniPick} onValueChange={pickMunicipality}>
            <SelectTrigger
              className="h-10 rounded-none bg-[#0a0a0a] border-[#8B5CF6]/40 text-xs"
              data-testid="courier-muni-picker-select"
            >
              <SelectValue placeholder={t("courier.muniPickPlaceholder")} />
            </SelectTrigger>
            <SelectContent className="bg-[#1A1730] border-white/10 text-white max-h-64">
              {(munis || []).map((m) => (
                <SelectItem key={m.id} value={m.municipality}>
                  {m.municipality} — {m.price_usdt} USDT
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {picked && (
        <p className="text-[0.65rem] text-neutral-500 truncate flex items-center gap-1" data-testid="courier-picked-address">
          <MapPin className="w-3 h-3 shrink-0" /> {picked.display_name}
        </p>
      )}
    </div>
  );
}
