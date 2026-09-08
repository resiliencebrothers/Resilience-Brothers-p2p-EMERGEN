import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { useLiveEvent } from "@/hooks/useLiveStream";
import { Html5Qrcode } from "html5-qrcode";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Plus, Edit2, Trash2, MapPin, Store, Footprints, PackageCheck, ScanLine } from "lucide-react";
import { toast } from "sonner";

const empty = { name: "", address: "", municipality: "", province: "", phone: "", hours: "", active: true };

// iter237 — panel para el personal: quién viene en camino y qué falta por recoger.
function PickupsPanel() {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  // iter238 — confirmación de entrega por código.
  const [code, setCode] = useState("");
  const [verified, setVerified] = useState(null);
  const [busy, setBusy] = useState(false);
  // iter239 — escáner QR de recogida (la entrega se confirma al escanear).
  const [scanOpen, setScanOpen] = useState(false);
  const scannerRef = useRef(null);
  const pendingRef = useRef(false);
  const lastRef = useRef({ code: "", ts: 0 });
  const load = () =>
    axios.get(`${API}/admin/pickups-today`, { withCredentials: true })
      .then((r) => setRows(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);
  useLiveEvent("pickups_changed", load);

  const verify = async () => {
    if (!code.trim()) return;
    setBusy(true);
    try {
      const r = await axios.get(`${API}/admin/pickups/verify`, {
        params: { code }, withCredentials: true,
      });
      setVerified(r.data);
    } catch (e) {
      setVerified(null);
      const d = e.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Error");
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await axios.post(`${API}/admin/pickups/confirm`, { code }, { withCredentials: true });
      toast.success(t("inventory.stores.codeConfirmedToast"));
      setCode(""); setVerified(null);
      load();
    } catch (e) {
      const d = e.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Error");
    } finally { setBusy(false); }
  };

  const stopScanner = async () => {
    try { await scannerRef.current?.stop(); scannerRef.current?.clear(); } catch { /* ya detenida */ }
    scannerRef.current = null;
  };

  const confirmScanned = async (raw) => {
    try {
      const r = await axios.post(`${API}/admin/pickups/confirm`, { code: raw }, { withCredentials: true });
      await stopScanner();
      setScanOpen(false);
      toast.success(t("inventory.stores.scanDeliveredToast", {
        name: r.data.user_name,
        product: `${r.data.quantity}× ${r.data.product_name}`,
      }));
      load();
    } catch (e) {
      const d = e.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Error");
      setTimeout(() => { pendingRef.current = false; }, 1500);
    }
  };

  const onScanDetected = (text) => {
    const raw = (text || "").trim();
    if (!raw || pendingRef.current) return;
    const now = Date.now();
    if (lastRef.current.code === raw && now - lastRef.current.ts < 2500) return;
    lastRef.current = { code: raw, ts: now };
    pendingRef.current = true;
    confirmScanned(raw);
  };

  const openScanner = async (isOpen) => {
    setScanOpen(isOpen);
    if (!isOpen) { await stopScanner(); return; }
    pendingRef.current = false;
    setTimeout(async () => {
      try {
        const s = new Html5Qrcode("pickup-scan-region");
        scannerRef.current = s;
        await s.start({ facingMode: "environment" },
          { fps: 10, qrbox: { width: 240, height: 240 } },
          onScanDetected, () => {});
      } catch {
        scannerRef.current = null;
        toast.error(t("inventory.stores.scanCameraError"));
      }
    }, 300);
  };
  useEffect(() => () => { stopScanner(); }, []);

  const onWay = rows.filter((r) => r.on_my_way_at);
  const pending = rows.filter((r) => !r.on_my_way_at);
  const fmtTime = (s) => {
    try { return new Date(s).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
    catch { return ""; }
  };

  const Row = ({ r, highlight }) => (
    <div
      data-testid={highlight ? `pickup-onway-row-${r.id}` : `pickup-pending-row-${r.id}`}
      className={`flex items-center justify-between gap-3 px-3 py-2 border ${
        highlight ? "border-amber-500/40 bg-amber-500/5" : "border-white/10"
      }`}
    >
      <div className="min-w-0">
        <div className="text-sm font-semibold truncate">{r.user_name}</div>
        <div className="text-xs text-neutral-400 truncate">
          {r.quantity}× {r.product_name}{r.store_name ? ` — ${r.store_name}` : ""}
        </div>
      </div>
      <div className="text-right shrink-0">
        {highlight ? (
          <span className="text-[0.65rem] text-amber-400 font-mono">
            {t("inventory.stores.notifiedAt")} {fmtTime(r.on_my_way_at)}
          </span>
        ) : r.pickup_ready_at ? (
          <span className="text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            {t("inventory.stores.readyTag")}
          </span>
        ) : (
          <span className="text-[0.6rem] uppercase tracking-wider px-1.5 py-0.5 bg-neutral-500/10 text-neutral-400 border border-neutral-500/30">
            {t("inventory.stores.preparingTag")}
          </span>
        )}
      </div>
    </div>
  );

  return (
    <div className="tactile-card p-5 space-y-4" data-testid="pickups-today-panel">
      <h3 className="font-display text-lg flex items-center gap-2">
        <PackageCheck className="w-5 h-5 text-[#8B5CF6]" /> {t("inventory.stores.pickupsTitle")}
      </h3>
      <div className="space-y-2">
        <p className="micro-label text-neutral-500">{t("inventory.stores.codeTitle")}</p>
        <div className="flex gap-2">
          <Input
            data-testid="pickup-code-input"
            value={code}
            onChange={(e) => { setCode(e.target.value.toUpperCase()); setVerified(null); }}
            onKeyDown={(e) => e.key === "Enter" && verify()}
            placeholder={t("inventory.stores.codePlaceholder")}
            className="rounded-none bg-[#0a0a0a] border-white/10 font-mono uppercase max-w-xs"
          />
          <Button data-testid="pickup-code-verify-btn" onClick={verify} disabled={busy || !code.trim()}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
            {t("inventory.stores.verifyBtn")}
          </Button>
          <Button data-testid="pickup-scan-qr-btn" onClick={() => openScanner(true)}
            className="bg-transparent border border-[#8B5CF6]/50 text-[#8B5CF6] hover:bg-[#8B5CF6]/10 rounded-none">
            <ScanLine className="w-4 h-4 mr-1" /> {t("inventory.stores.scanQrBtn")}
          </Button>
        </div>
        {verified && (
          <div data-testid="pickup-verify-result"
            className="flex items-center justify-between gap-3 px-3 py-2 border border-emerald-500/40 bg-emerald-500/5">
            <div className="min-w-0">
              <div className="text-sm font-semibold truncate">{verified.user_name}</div>
              <div className="text-xs text-neutral-400 truncate">
                {verified.quantity}× {verified.product_name}{verified.store_name ? ` — ${verified.store_name}` : ""}
              </div>
            </div>
            <Button data-testid="pickup-confirm-btn" onClick={confirm} disabled={busy}
              className="bg-[#22C55E] hover:bg-emerald-400 text-black rounded-none shrink-0">
              {t("inventory.stores.confirmBtn")}
            </Button>
          </div>
        )}
      </div>
      {rows.length === 0 && (
        <p className="text-sm text-neutral-500" data-testid="pickups-empty">
          {t("inventory.stores.pickupsEmpty")}
        </p>
      )}
      {onWay.length > 0 && (
        <div className="space-y-2">
          <p className="micro-label text-amber-400 flex items-center gap-1.5">
            <Footprints className="w-3.5 h-3.5" /> {t("inventory.stores.onTheWayNow")} ({onWay.length})
          </p>
          {onWay.map((r) => <Row key={r.id} r={r} highlight />)}
        </div>
      )}
      {pending.length > 0 && (
        <div className="space-y-2">
          <p className="micro-label text-neutral-500">
            {t("inventory.stores.pendingPickups")} ({pending.length})
          </p>
          {pending.map((r) => <Row key={r.id} r={r} />)}
        </div>
      )}

      <Dialog open={scanOpen} onOpenChange={openScanner}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-display">{t("inventory.stores.scanTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3" data-testid="pickup-scan-dialog">
            <div id="pickup-scan-region" className="w-full min-h-[260px] bg-black" />
            <p className="text-[0.65rem] text-neutral-500">{t("inventory.stores.scanHint")}</p>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// iter236 — CRUD de sucursales físicas para la recogida en tienda.
export default function InventoryStoresTab() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);

  const load = () =>
    axios.get(`${API}/admin/stores`, { withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!form.name.trim()) return toast.error(t("inventory.stores.nameRequired"));
    if (!form.address.trim()) return toast.error(t("inventory.stores.addressRequired"));
    setBusy(true);
    try {
      if (editing) await axios.put(`${API}/admin/stores/${editing.id}`, form, { withCredentials: true });
      else await axios.post(`${API}/admin/stores`, form, { withCredentials: true });
      toast.success(t("inventory.stores.toastSaved"));
      setOpen(false); setEditing(null); setForm(empty);
      load();
    } catch (e) {
      const d = e.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Error");
    } finally { setBusy(false); }
  };

  const remove = async (id) => {
    if (!window.confirm(t("inventory.stores.confirmDelete"))) return;
    try {
      await axios.delete(`${API}/admin/stores/${id}`, { withCredentials: true });
      toast.success(t("inventory.stores.toastDeleted"));
      load();
    } catch (e) {
      const d = e.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Error");
    }
  };

  return (
    <div data-testid="inventory-stores-tab" className="space-y-4">
      <PickupsPanel />
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="font-display text-xl flex items-center gap-2">
            <Store className="w-5 h-5 text-[#8B5CF6]" /> {t("inventory.stores.title")}
          </h2>
          <p className="text-sm text-neutral-500 mt-1">{t("inventory.stores.subtitle")}</p>
        </div>
        <Button
          data-testid="stores-tab-add-btn"
          onClick={() => { setEditing(null); setForm(empty); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
        >
          <Plus className="w-4 h-4 mr-1" /> {t("inventory.stores.addBtn")}
        </Button>
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-10 tactile-card" data-testid="stores-empty">
          {t("inventory.stores.empty")}
        </p>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((s) => (
          <div key={s.id} className="tactile-card p-5 space-y-2" data-testid={`store-row-${s.id}`}>
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-display text-lg flex items-center gap-2">
                <MapPin className="w-4 h-4 text-[#8B5CF6]" /> {s.name}
              </h3>
              <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${s.active ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" : "bg-neutral-500/10 text-neutral-400 border-neutral-500/30"}`}>
                {s.active ? t("inventory.stores.activeBadge") : t("inventory.stores.inactiveBadge")}
              </span>
            </div>
            <p className="text-sm text-neutral-300">{s.address}</p>
            <p className="text-xs text-neutral-500">
              {[s.municipality, s.province].filter(Boolean).join(", ")}
            </p>
            {(s.hours || s.phone) && (
              <p className="text-xs text-neutral-500 font-mono">
                {[s.hours, s.phone].filter(Boolean).join(" · ")}
              </p>
            )}
            <div className="flex gap-3 pt-1">
              <button
                data-testid={`store-edit-${s.id}`}
                onClick={() => { setEditing(s); setForm({ ...empty, ...s }); setOpen(true); }}
                className="text-neutral-400 hover:text-[#8B5CF6]"
              >
                <Edit2 className="w-4 h-4" />
              </button>
              <button
                data-testid={`store-delete-${s.id}`}
                onClick={() => remove(s.id)}
                className="text-neutral-400 hover:text-[#EF4444]"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">
              {editing ? t("inventory.stores.editTitle") : t("inventory.stores.newTitle")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.stores.name")}</Label>
              <Input data-testid="store-name-input" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("inventory.stores.address")}</Label>
              <Textarea data-testid="store-address-input" value={form.address} rows={2}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.stores.municipality")}</Label>
                <Input data-testid="store-muni-input" value={form.municipality}
                  onChange={(e) => setForm({ ...form, municipality: e.target.value })}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.stores.province")}</Label>
                <Input data-testid="store-province-input" value={form.province}
                  onChange={(e) => setForm({ ...form, province: e.target.value })}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.stores.phone")}</Label>
                <Input data-testid="store-phone-input" value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("inventory.stores.hours")}</Label>
                <Input data-testid="store-hours-input" value={form.hours}
                  onChange={(e) => setForm({ ...form, hours: e.target.value })}
                  placeholder="Lun-Sáb 9:00-17:00"
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Switch data-testid="store-active-switch" checked={form.active}
                onCheckedChange={(v) => setForm({ ...form, active: v })} />
              <span className="text-sm">{t("inventory.stores.active")}</span>
            </div>
            <Button data-testid="store-save-btn" onClick={save} disabled={busy}
              className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none">
              {t("inventory.stores.save")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
