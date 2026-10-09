import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  Printer, Inbox, FlaskConical, Wifi, MonitorSmartphone, Receipt, Loader2,
} from "lucide-react";
import {
  loadPrinterConfig, savePrinterConfig, sendEscposToSunmi,
  printPlaintextInBrowser, hexPreview,
} from "@/lib/receiptPrinter";

const money = (n, c) => `${Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${c}`;
const when = (s) => (s ? new Date(s).toLocaleString() : "—");

// iter356 — Caja / Impresión: ticket + gaveta para SUNMI D3 Mini T1730.
export default function InventoryPrintTab() {
  const { t } = useTranslation();
  const [cfg, setCfg] = useState(loadPrinterConfig());
  const [sales, setSales] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);

  const set = (k, v) => setCfg((c) => { const n = { ...c, [k]: v }; savePrinterConfig(n); return n; });

  const loadSales = useCallback(() => {
    axios.get(`${API}/admin/inventory/movements?type=venta&limit=15`, { withCredentials: true })
      .then((r) => setSales(r.data || []))
      .catch(() => setSales([]));
  }, []);
  useEffect(() => { loadSales(); }, [loadSales]);

  // Enruta el ESC/POS ya construido según el transporte configurado.
  const route = async (built, kind) => {
    setPreview({ ...built, kind });
    if (cfg.transport === "sunmi") {
      setSending(true);
      try {
        await sendEscposToSunmi(built.escpos_b64, cfg.sunmiWsUrl);
        toast.success(t("inventory.print.sentSunmi"));
        setPreview((p) => (p ? { ...p, result: "ok" } : p));
      } catch (e) {
        toast.error(e.message);
        setPreview((p) => (p ? { ...p, result: "error", error: e.message } : p));
      } finally { setSending(false); }
    } else if (cfg.transport === "navegador") {
      try { printPlaintextInBrowser(built.plaintext); } catch (e) { toast.error(e.message); }
    } else {
      toast.success(t("inventory.print.simOk"));
    }
  };

  const printSample = async () => {
    setBusy(true);
    try {
      const { data } = await axios.get(
        `${API}/admin/pos/receipt/sample?width=${cfg.width}&open_drawer=${cfg.openDrawer}&print_logo=${cfg.printLogo}`,
        { withCredentials: true });
      await route(data, "sample");
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  const printSale = async (mv) => {
    setBusy(true);
    try {
      // SUN-03-B: una reimpresión es una COPIA, no el evento de caja original.
      // NUNCA abre la gaveta (ignora cfg.openDrawer y preferencias antiguas).
      // Solo el botón manual "Abrir gaveta" —o, en el futuro, el cobro real—
      // dispara el pulso. El ticket de prueba sí respeta su propio toggle.
      const payload = {
        business_name: cfg.business_name, business_line2: cfg.business_line2,
        business_line3: cfg.business_line3, footer: cfg.footer,
        currency: cfg.currency, width: cfg.width, open_drawer: false,
        print_logo: cfg.printLogo,
        ticket_no: String(mv.id).slice(0, 8).toUpperCase(),
        datetime: when(mv.created_at), cashier: mv.actor_email || "",
        items: [{
          name: mv.product_name || mv.product_id, qty: mv.quantity,
          unit: mv.unit || "", unit_price: mv.unit_price || 0, total: mv.total || 0,
        }],
        subtotal: mv.total || 0, total: mv.total || 0,
      };
      const { data } = await axios.post(
        `${API}/admin/pos/receipt/build`, payload, { withCredentials: true });
      await route(data, "sale");
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  const openDrawer = async () => {
    setBusy(true);
    try {
      const { data } = await axios.get(`${API}/admin/pos/drawer/open`, { withCredentials: true });
      if (cfg.transport === "sunmi") {
        setSending(true);
        try { await sendEscposToSunmi(data.escpos_b64, cfg.sunmiWsUrl); toast.success(t("inventory.print.drawerSent")); }
        catch (e) { toast.error(e.message); } finally { setSending(false); }
      } else {
        toast.message(t("inventory.print.drawerSim"), { description: hexPreview(data.escpos_b64) });
      }
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };

  const transports = [
    { k: "simulacion", icon: FlaskConical, label: t("inventory.print.tSim") },
    { k: "sunmi", icon: Wifi, label: t("inventory.print.tSunmi") },
    { k: "navegador", icon: MonitorSmartphone, label: t("inventory.print.tBrowser") },
  ];

  return (
    <div className="space-y-6" data-testid="inventory-print-view">
      <div className="flex items-center gap-2">
        <Printer className="w-5 h-5 text-[#8B5CF6]" />
        <h3 className="text-sm uppercase tracking-wider text-white">{t("inventory.print.title")}</h3>
      </div>
      <p className="text-[0.7rem] text-neutral-400 max-w-2xl">{t("inventory.print.intro")}</p>

      {/* Modo actual */}
      <div className={`flex items-start gap-2 px-3 py-2 border text-[0.7rem] ${
        cfg.transport === "sunmi" ? "border-amber-500/30 bg-amber-500/5 text-amber-200"
          : "border-sky-500/25 bg-sky-500/5 text-sky-200"}`}
        data-testid="print-mode-banner">
        {cfg.transport === "sunmi"
          ? t("inventory.print.bannerSunmi")
          : cfg.transport === "navegador" ? t("inventory.print.bannerBrowser")
            : t("inventory.print.bannerSim")}
      </div>

      {/* Configuración */}
      <div className="border border-white/10 bg-white/[0.02] p-4 space-y-4" data-testid="print-config">
        <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{t("inventory.print.transport")}</div>
        <div className="flex flex-wrap gap-2">
          {transports.map(({ k, icon: Icon, label }) => (
            <button key={k} type="button" onClick={() => set("transport", k)}
              data-testid={`print-transport-${k}`}
              className={`flex items-center gap-2 px-3 py-1.5 text-xs border transition-colors ${
                cfg.transport === k ? "border-[#8B5CF6] bg-[#8B5CF6]/15 text-white"
                  : "border-white/10 text-neutral-400 hover:text-white"}`}>
              <Icon className="w-3.5 h-3.5" /> {label}
            </button>
          ))}
        </div>

        {cfg.transport === "sunmi" && (
          <div className="text-[0.65rem] text-amber-200/90 bg-amber-500/5 border border-amber-500/20 px-3 py-2"
            data-testid="print-jsusdk-note">
            {t("inventory.print.jsusdkNote")}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1">
            <Label className="text-[0.65rem] text-neutral-400">{t("inventory.print.paper")}</Label>
            <div className="flex gap-2">
              {[{ w: 48, l: "80mm" }, { w: 32, l: "58mm" }].map(({ w, l }) => (
                <button key={w} type="button" onClick={() => set("width", w)}
                  data-testid={`print-width-${w}`}
                  className={`px-3 py-1.5 text-xs border ${cfg.width === w
                    ? "border-[#8B5CF6] bg-[#8B5CF6]/15 text-white" : "border-white/10 text-neutral-400"}`}>
                  {l}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-3 pt-5">
            <div className="flex items-center justify-between sm:justify-start sm:gap-4">
              <Label className="text-[0.7rem] text-neutral-300">{t("inventory.print.openDrawerToggle")}</Label>
              <Switch checked={cfg.openDrawer} onCheckedChange={(v) => set("openDrawer", v)}
                data-testid="print-drawer-toggle" />
            </div>
            <div className="flex items-center justify-between sm:justify-start sm:gap-4">
              <Label className="text-[0.7rem] text-neutral-300">{t("inventory.print.logoToggle")}</Label>
              <Switch checked={cfg.printLogo} onCheckedChange={(v) => set("printLogo", v)}
                data-testid="print-logo-toggle" />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-[0.65rem] text-neutral-400">{t("inventory.print.bizName")}</Label>
            <Input value={cfg.business_name} onChange={(e) => set("business_name", e.target.value)}
              data-testid="print-biz-name" className="bg-black/30 border-white/10 text-sm rounded-none" />
          </div>
          <div className="space-y-1">
            <Label className="text-[0.65rem] text-neutral-400">{t("inventory.print.bizLine2")}</Label>
            <Input value={cfg.business_line2} onChange={(e) => set("business_line2", e.target.value)}
              data-testid="print-biz-line2" className="bg-black/30 border-white/10 text-sm rounded-none" />
          </div>
        </div>
      </div>

      {/* Acciones de prueba */}
      <div className="flex flex-wrap gap-2">
        <Button onClick={printSample} disabled={busy}
          data-testid="print-sample-btn"
          className="bg-[#8B5CF6] hover:bg-[#7c4df0] text-white rounded-none text-xs">
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Receipt className="w-3.5 h-3.5 mr-1" />}
          {t("inventory.print.testTicket")}
        </Button>
        <Button onClick={openDrawer} disabled={busy} variant="outline"
          data-testid="print-open-drawer-btn"
          className="border-white/10 text-neutral-200 rounded-none text-xs">
          <Inbox className="w-3.5 h-3.5 mr-1" /> {t("inventory.print.openDrawer")}
        </Button>
      </div>

      {/* Imprimir desde una venta reciente */}
      <div className="border border-white/10 bg-white/[0.02]">
        <div className="px-4 py-2.5 border-b border-white/10 text-sm text-white">
          {t("inventory.print.recentSales")}
        </div>
        <div className="divide-y divide-white/5">
          {sales.length === 0 && (
            <div className="px-4 py-6 text-center text-[0.7rem] text-neutral-500">
              {t("inventory.print.noSales")}
            </div>
          )}
          {sales.map((mv) => (
            <div key={mv.id} className="flex items-center gap-3 px-4 py-2.5 flex-wrap"
              data-testid={`print-sale-${mv.id}`}>
              <div className="min-w-0 flex-1">
                <div className="text-sm text-neutral-200 truncate">{mv.product_name || mv.product_id}</div>
                <div className="text-[0.65rem] text-neutral-500">
                  {Number(mv.quantity).toLocaleString()} {mv.unit} · {money(mv.total, cfg.currency)} · {when(mv.created_at)}
                </div>
              </div>
              <Button size="sm" onClick={() => printSale(mv)} disabled={busy}
                data-testid={`print-sale-btn-${mv.id}`}
                className="bg-white/5 hover:bg-[#8B5CF6]/20 text-neutral-200 rounded-none text-xs border border-white/10">
                <Printer className="w-3.5 h-3.5 mr-1" /> {t("inventory.print.printTicket")}
              </Button>
            </div>
          ))}
        </div>
      </div>

      {/* Vista de simulación del ticket */}
      <Dialog open={!!preview} onOpenChange={(o) => { if (!o) setPreview(null); }}>
        <DialogContent className="bg-[#0d0d12] border-white/10 max-w-md max-h-[85vh] overflow-y-auto"
          data-testid="print-preview-dialog">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Receipt className="w-4 h-4" /> {t("inventory.print.previewTitle")}
            </DialogTitle>
            <DialogDescription className="text-neutral-400 text-xs">
              {cfg.transport === "simulacion" ? t("inventory.print.previewDescSim")
                : cfg.transport === "sunmi" ? t("inventory.print.previewDescSunmi")
                  : t("inventory.print.previewDescBrowser")}
            </DialogDescription>
          </DialogHeader>
          {preview && (
            <div className="space-y-3">
              {sending && (
                <div className="flex items-center gap-2 text-xs text-amber-300">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t("inventory.print.sending")}
                </div>
              )}
              {preview.result === "ok" && (
                <div className="text-xs text-emerald-400" data-testid="print-result-ok">✓ {t("inventory.print.sentSunmi")}</div>
              )}
              {preview.result === "error" && (
                <div className="text-xs text-rose-400" data-testid="print-result-error">✕ {preview.error}</div>
              )}
              <pre className="bg-white text-black text-[11px] leading-tight font-mono p-3 overflow-x-auto whitespace-pre"
                data-testid="print-preview-paper">{preview.plaintext}</pre>
              {preview.open_drawer && (
                <div className="text-[0.65rem] text-amber-300" data-testid="print-preview-drawer">
                  {t("inventory.print.drawerIncluded")}
                </div>
              )}
              {preview.has_logo && (
                <div className="text-[0.65rem] text-sky-300" data-testid="print-preview-logo">
                  {t("inventory.print.logoIncluded")}
                </div>
              )}
              <details className="text-[0.6rem] text-neutral-500">
                <summary className="cursor-pointer">{t("inventory.print.escposDump")} ({preview.escpos_len} bytes)</summary>
                <code className="block mt-1 break-all" data-testid="print-escpos-hex">{hexPreview(preview.escpos_b64)}</code>
              </details>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
