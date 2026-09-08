import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Html5Qrcode } from "html5-qrcode";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Camera, CameraOff, ScanBarcode, Link2, PackagePlus, ShoppingCart } from "lucide-react";
import { toast } from "sonner";
import { playCashSound } from "@/utils/cashSound";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// iter227 — escáner de código de barras: modo fijo (venta/entrada), cámara del
// móvil o webcam, ráfaga (la cámara sigue activa tras cada registro) y
// vinculación de códigos nuevos a productos existentes.
export default function InventoryScanTab() {
  const { t } = useTranslation();
  const [mode, setMode] = useState("venta");
  const [cameraOn, setCameraOn] = useState(false);
  const [products, setProducts] = useState([]);
  const [manual, setManual] = useState("");
  const [hit, setHit] = useState(null);
  const [unknown, setUnknown] = useState(null);
  const [assignId, setAssignId] = useState("");
  const [qty, setQty] = useState(1);
  const [unitVal, setUnitVal] = useState("");
  const [busy, setBusy] = useState(false);
  const scannerRef = useRef(null);
  const pendingRef = useRef(false);
  const lastRef = useRef({ code: "", ts: 0 });

  useEffect(() => {
    axios.get(`${API}/admin/inventory/control`, { withCredentials: true })
      .then((r) => setProducts(r.data)).catch(() => {});
    return () => { try { scannerRef.current?.stop(); } catch { /* ya detenida */ } };
  }, []);

  const lookup = async (code) => {
    try {
      const r = await axios.get(`${API}/admin/inventory/barcode/${encodeURIComponent(code)}`, { withCredentials: true });
      setUnknown(null); setHit(r.data); setQty(1); setUnitVal("");
    } catch (e) {
      if (e.response?.status === 404) { setHit(null); setUnknown(code); setAssignId(""); }
      else { toast.error(e.response?.data?.detail || t("inventory.scan.lookupError")); pendingRef.current = false; }
    }
  };

  const onDetected = (text) => {
    const code = (text || "").trim();
    if (!code || pendingRef.current) return;
    const now = Date.now();
    if (lastRef.current.code === code && now - lastRef.current.ts < 2500) return;
    lastRef.current = { code, ts: now };
    pendingRef.current = true;
    lookup(code);
  };

  const startCamera = async () => {
    try {
      const s = new Html5Qrcode("inv-scan-region");
      scannerRef.current = s;
      await s.start({ facingMode: "environment" }, { fps: 10, qrbox: { width: 280, height: 160 } },
        onDetected, () => {});
      setCameraOn(true);
    } catch {
      scannerRef.current = null;
      toast.error(t("inventory.scan.cameraError"));
    }
  };

  const stopCamera = async () => {
    try { await scannerRef.current?.stop(); scannerRef.current?.clear(); } catch { /* ya detenida */ }
    scannerRef.current = null;
    setCameraOn(false);
  };

  const resume = () => { setHit(null); setUnknown(null); pendingRef.current = false; };

  const manualSearch = () => {
    const code = manual.trim();
    if (!code) return;
    pendingRef.current = true;
    setManual("");
    lookup(code);
  };

  const register = async () => {
    const q = parseInt(qty);
    if (!q || q <= 0) return toast.error(t("inventory.scan.qtyRequired"));
    setBusy(true);
    try {
      const payload = { product_id: hit.product_id, type: mode, quantity: q, note: t("inventory.scan.noteScanner") };
      if (unitVal !== "") {
        if (mode === "venta") payload.unit_price = parseFloat(unitVal);
        else payload.unit_cost = parseFloat(unitVal);
      }
      await axios.post(`${API}/admin/inventory/movements`, payload, { withCredentials: true });
      if (mode === "venta") playCashSound();
      toast.success(t("inventory.scan.registered", {
        name: hit.name,
        mode: mode === "venta" ? t("inventory.movements.typeVenta") : t("inventory.movements.typeEntrada"),
      }));
      resume();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const assign = async () => {
    if (!assignId) return toast.error(t("inventory.scan.assignRequired"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/admin/inventory/barcode/assign`,
        { product_id: assignId, barcode: unknown }, { withCredentials: true });
      toast.success(t("inventory.scan.assigned", { name: r.data.name }));
      await lookup(unknown);
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const modeBtn = (k, Icon, label) => (
    <button
      data-testid={`scan-mode-${k}`}
      onClick={() => setMode(k)}
      className={`flex-1 h-11 flex items-center justify-center gap-2 text-xs uppercase tracking-wider border transition-colors ${
        mode === k
          ? (k === "venta" ? "bg-amber-500/20 border-amber-400 text-amber-300" : "bg-emerald-500/20 border-emerald-400 text-emerald-300")
          : "border-white/15 text-neutral-400 hover:text-white"
      }`}
    >
      <Icon className="w-4 h-4" /> {label}
    </button>
  );

  return (
    <div className="grid lg:grid-cols-2 gap-4" data-testid="inventory-scan-tab">
      <div className="space-y-4">
        <div className="flex gap-2" data-testid="scan-mode-toggle">
          {modeBtn("venta", ShoppingCart, t("inventory.scan.modeVenta"))}
          {modeBtn("entrada", PackagePlus, t("inventory.scan.modeEntrada"))}
        </div>
        <p className="text-xs text-neutral-500">
          {t("inventory.scan.modeHint", {
            mode: mode === "venta" ? t("inventory.movements.typeVenta") : t("inventory.movements.typeEntrada"),
          })}
        </p>
        <div className="tactile-card p-3 space-y-3">
          <div id="inv-scan-region" className="w-full min-h-[120px] bg-[#0a0a0a] border border-white/10" />
          {!cameraOn ? (
            <Button data-testid="scan-start-camera" onClick={startCamera}
              className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-11">
              <Camera className="w-4 h-4 mr-2" /> {t("inventory.scan.startCamera")}
            </Button>
          ) : (
            <>
              <p className="text-xs text-center text-neutral-400 animate-pulse">{t("inventory.scan.scanning")}</p>
              <Button data-testid="scan-stop-camera" onClick={stopCamera} variant="outline"
                className="w-full rounded-none border-white/15 h-10">
                <CameraOff className="w-4 h-4 mr-2" /> {t("inventory.scan.stopCamera")}
              </Button>
            </>
          )}
        </div>
        <div>
          <Label className="micro-label text-neutral-500">{t("inventory.scan.manualLabel")}</Label>
          <div className="flex gap-2 mt-1">
            <Input data-testid="scan-manual-input" value={manual}
              onChange={(e) => setManual(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && manualSearch()}
              placeholder={t("inventory.scan.manualPlaceholder")}
              className="rounded-none bg-[#0a0a0a] border-white/10 font-mono h-10" />
            <Button data-testid="scan-manual-search" onClick={manualSearch}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-10">
              {t("inventory.scan.manualSearch")}
            </Button>
          </div>
        </div>
      </div>

      <div>
        {!hit && !unknown && (
          <div className="tactile-card p-8 h-full flex flex-col items-center justify-center text-center gap-3" data-testid="scan-placeholder">
            <ScanBarcode className="w-10 h-10 text-neutral-600" />
            <p className="text-sm text-neutral-500">{t("inventory.scan.placeholder")}</p>
          </div>
        )}
        {hit && (
          <div className="tactile-card p-5 space-y-4" data-testid="scan-hit-card">
            <div className="flex items-start gap-4">
              {hit.image_url && <img src={hit.image_url} alt={hit.name} className="w-16 h-16 object-cover border border-white/10" />}
              <div>
                <p className="font-display text-lg" data-testid="scan-hit-name">{hit.name}</p>
                <p className="text-xs text-neutral-500 font-mono">{t("inventory.scan.barcodeLabel")}: {hit.barcode}</p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="border border-white/10 py-2">
                <p className="micro-label text-neutral-500">{t("inventory.scan.foundStock")}</p>
                <p className="font-mono text-lg" data-testid="scan-hit-stock">{hit.stock}</p>
              </div>
              <div className="border border-white/10 py-2">
                <p className="micro-label text-neutral-500">{t("inventory.scan.foundPrice")}</p>
                <p className="font-mono text-lg text-[#8B5CF6]">{fmt(hit.price_usd)}</p>
              </div>
              <div className="border border-white/10 py-2">
                <p className="micro-label text-neutral-500">{t("inventory.scan.foundCost")}</p>
                <p className="font-mono text-lg text-neutral-400">{fmt(hit.cost_usd)}</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.scan.qty")}</Label>
                <Input data-testid="scan-qty" type="number" min="1" value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">
                  {mode === "venta" ? t("inventory.scan.unitPrice") : t("inventory.scan.unitCost")}
                </Label>
                <Input data-testid="scan-unit-value" type="number" step="any" min="0" value={unitVal}
                  placeholder={t("inventory.movements.defaultFromProduct")}
                  onChange={(e) => setUnitVal(e.target.value)}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
              </div>
            </div>
            <Button data-testid="scan-register-btn" onClick={register} disabled={busy}
              className={`w-full text-white font-bold rounded-none h-12 ${mode === "venta" ? "bg-amber-600 hover:bg-amber-500" : "bg-emerald-700 hover:bg-emerald-600"}`}>
              {busy ? "…" : (mode === "venta" ? t("inventory.scan.registerVenta") : t("inventory.scan.registerEntrada"))}
            </Button>
            <button data-testid="scan-keep-scanning" onClick={resume}
              className="w-full text-xs text-neutral-400 hover:text-white underline">
              {t("inventory.scan.keepScanning")}
            </button>
          </div>
        )}
        {unknown && (
          <div className="tactile-card p-5 space-y-4 border-amber-500/30" data-testid="scan-unknown-panel">
            <div className="flex items-center gap-2 text-amber-300">
              <Link2 className="w-4 h-4" />
              <p className="text-sm font-bold" data-testid="scan-unknown-code">{t("inventory.scan.unknownTitle", { code: unknown })}</p>
            </div>
            <p className="text-xs text-neutral-400">{t("inventory.scan.unknownHint")}</p>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.scan.assignSelect")}</Label>
              <select data-testid="scan-assign-select" value={assignId}
                onChange={(e) => setAssignId(e.target.value)}
                className="w-full h-10 mt-1 bg-[#0a0a0a] border border-white/10 text-sm px-3 text-white">
                <option value="">—</option>
                {products.map((p) => <option key={p.product_id} value={p.product_id}>{`${p.name} (stock ${p.stock})`}</option>)}
              </select>
            </div>
            <Button data-testid="scan-assign-btn" onClick={assign} disabled={busy}
              className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {busy ? "…" : t("inventory.scan.assignBtn")}
            </Button>
            <button data-testid="scan-unknown-cancel" onClick={resume}
              className="w-full text-xs text-neutral-400 hover:text-white underline">
              {t("inventory.scan.keepScanning")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
