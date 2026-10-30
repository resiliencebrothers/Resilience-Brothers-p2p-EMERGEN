import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Truck, Plus, MapPin, Package, User } from "lucide-react";
import { toast } from "sonner";

// Fase 4 — la Empresa SOLICITA mensajería; Resilience asigna el mensajero.
// La Empresa no elige ni asigna mensajeros.
const STATUS_CLS = {
  available: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  assigned: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  accepted: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  on_the_way: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
  delivered: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  confirmed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  cancelled: "bg-neutral-500/10 text-neutral-400 border-neutral-500/30",
};
const CANCELABLE = ["available", "assigned"];
const emptyForm = {
  receiver_name: "", receiver_phone: "", delivery_address: "", province: "",
  municipality: "", note: "", fromStore: false, product_id: "", origin_store_id: "", quantity: "",
};

export default function CompanyDeliveriesView() {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [products, setProducts] = useState([]);
  const [stores, setStores] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [fee, setFee] = useState(0);
  const clientKeyRef = useRef(null);

  const load = useCallback(() => {
    axios.get(`${API}/company/deliveries`, { withCredentials: true }).then((r) => setItems(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/company/me`, { withCredentials: true }).then((r) => setFee(Number(r.data?.delivery_fee_usdt || 0))).catch(() => {});
    axios.get(`${API}/company/products`, { withCredentials: true }).then((r) => setProducts(r.data)).catch(() => {});
    axios.get(`${API}/company/stores`, { withCredentials: true }).then((r) => setStores(r.data)).catch(() => {});
  }, [load]);

  const submit = async () => {
    if (!form.receiver_name || form.receiver_name.trim().length < 2) return toast.error(t("company.deliveries.receiverRequired"));
    if (!form.receiver_phone) return toast.error(t("company.deliveries.phoneRequired"));
    if (!form.delivery_address || form.delivery_address.trim().length < 5) return toast.error(t("company.deliveries.addressRequired"));
    // E34-02 — clave de idempotencia ESTABLE por envío lógico: se genera UNA
    // vez y se conserva en los reintentos (mismo envío ⇒ mismo cargo/reserva).
    if (!clientKeyRef.current) {
      clientKeyRef.current = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
    }
    const body = {
      receiver_name: form.receiver_name.trim(),
      receiver_phone: form.receiver_phone.trim(),
      delivery_address: form.delivery_address.trim(),
      province: form.province || "",
      municipality: form.municipality || "",
      note: form.note || "",
      client_key: clientKeyRef.current,
    };
    if (form.fromStore) {
      if (!form.product_id || !form.origin_store_id || !form.quantity) return toast.error(t("company.deliveries.fromStoreIncomplete"));
      body.product_id = form.product_id;
      body.origin_store_id = form.origin_store_id;
      body.quantity = parseFloat(form.quantity);
    }
    setBusy(true);
    const doPost = () => axios.post(`${API}/company/deliveries`, body, { withCredentials: true });
    try {
      try {
        await doPost();
      } catch (e1) {
        // Sin respuesta del servidor (red): reintenta UNA vez con la MISMA
        // clave → el backend deduplica (no se cobra ni reserva dos veces).
        if (!e1.response) { await doPost(); } else { throw e1; }
      }
      toast.success(t("company.deliveries.requestSent"));
      clientKeyRef.current = null;  // nuevo envío ⇒ nueva clave
      setOpen(false); setForm(emptyForm); load();
    } catch (e) {
      // R09 — si el backend revirtió este intento (failed_init) o la clave ya se
      // usó para OTRO envío (conflicto de payload), descarta la clave para que
      // un nuevo intento obtenga una IDENTIDAD nueva (no reutilice la anterior).
      if (e.response?.status === 409) clientKeyRef.current = null;
      toast.error(e.response?.data?.detail || t("company.deliveries.createFailed"));
    } finally { setBusy(false); }
  };

  const cancel = async (it) => {
    if (!window.confirm(t("company.deliveries.confirmCancel"))) return;
    try {
      await axios.post(`${API}/company/deliveries/${it.id}/cancel`, {}, { withCredentials: true });
      toast.success(t("company.deliveries.cancelled"));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || t("company.deliveries.cancelFailed")); }
  };

  return (
    <div className="space-y-6" data-testid="company-deliveries-view">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-2">{t("company.deliveries.sectionLabel")}</div>
          <h2 className="font-display text-2xl flex items-center gap-3">
            <Truck className="w-6 h-6 text-[#8B5CF6]" /> {t("company.deliveries.title")}
          </h2>
          <p className="text-sm text-neutral-500 mt-1">{t("company.deliveries.subtitle")}</p>
          <p className="text-xs mt-1" data-testid="company-delivery-fee-note">
            {fee > 0
              ? <span className="text-amber-300">{t("company.deliveries.feeNoteWithFeePre")}<span className="font-mono">{fee} USDT</span>{t("company.deliveries.feeNoteWithFeePost")}</span>
              : <span className="text-emerald-400">{t("company.deliveries.feeNoteFree")}</span>}
          </p>
        </div>
        <Button data-testid="company-delivery-new-btn" onClick={() => { setForm(emptyForm); setOpen(true); }}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none">
          <Plus className="w-4 h-4 mr-1" /> {t("company.deliveries.newBtn")}
        </Button>
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-deliveries-empty">
          {t("company.deliveries.empty")}
        </p>
      )}

      <div className="space-y-3">
        {items.map((it) => {
          const cls = STATUS_CLS[it.delivery_status] || STATUS_CLS.available;
          const label = t(`company.deliveries.status.${it.delivery_status}`, { defaultValue: t("company.deliveries.status.available") });
          return (
            <div key={it.id} className="tactile-card p-4" data-testid={`company-delivery-${it.id}`}>
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-sm"><User className="w-4 h-4 text-neutral-600" /> <span className="text-white">{it.receiver_name}</span> <span className="text-neutral-500">· {it.receiver_phone}</span></div>
                  <div className="flex items-start gap-2 text-sm text-neutral-400"><MapPin className="w-4 h-4 mt-0.5 text-neutral-600" /> {it.delivery_address}{it.municipality ? `, ${it.municipality}` : ""}{it.province ? `, ${it.province}` : ""}</div>
                  <div className="flex items-center gap-2 text-sm text-neutral-400"><Package className="w-4 h-4 text-neutral-600" /> {it.package_label}</div>
                  {it.courier_name && <div className="text-xs text-sky-300">{t("company.deliveries.courierPrefix")} {it.courier_name}</div>}
                  {Number(it.fee_usdt || 0) > 0 && (
                    <div className="text-xs text-neutral-500" data-testid={`company-delivery-fee-${it.id}`}>
                      {t("company.deliveries.feePrefix")} <span className="font-mono text-neutral-300">{it.fee_usdt} USDT</span>
                      {it.fee_status === "held" && <span className="text-amber-300"> · {t("company.deliveries.feeHeld")}</span>}
                      {it.fee_status === "charged" && <span className="text-emerald-400"> · {t("company.deliveries.feeCharged")}</span>}
                      {it.fee_status === "refunded" && <span className="text-neutral-400"> · {t("company.deliveries.feeRefunded")}</span>}
                    </div>
                  )}
                </div>
                <div className="flex flex-col items-end gap-2">
                  <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${cls}`} data-testid={`company-delivery-status-${it.id}`}>{label}</span>
                  {CANCELABLE.includes(it.delivery_status) && (
                    <button data-testid={`company-delivery-cancel-${it.id}`} onClick={() => cancel(it)} className="text-xs text-neutral-400 hover:text-[#EF4444]">{t("company.deliveries.cancel")}</button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setOpen(false)}>
          <div className="bg-[#1A1730] border border-white/10 rounded-none w-full max-w-lg max-h-[88vh] overflow-y-auto p-6 space-y-3" onClick={(e) => e.stopPropagation()} data-testid="company-delivery-dialog">
            <h3 className="font-display text-xl">{t("company.deliveries.dialogTitle")}</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("company.deliveries.receiver")}</Label>
                <Input data-testid="company-delivery-receiver" value={form.receiver_name} onChange={(e) => setForm({ ...form, receiver_name: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.deliveries.phone")}</Label>
                <Input data-testid="company-delivery-phone" value={form.receiver_phone} onChange={(e) => setForm({ ...form, receiver_phone: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.deliveries.address")}</Label>
              <Input data-testid="company-delivery-address" value={form.delivery_address} onChange={(e) => setForm({ ...form, delivery_address: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="micro-label text-neutral-500">{t("company.deliveries.province")}</Label>
                <Input data-testid="company-delivery-province" value={form.province} onChange={(e) => setForm({ ...form, province: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
              <div>
                <Label className="micro-label text-neutral-500">{t("company.deliveries.municipality")}</Label>
                <Input data-testid="company-delivery-municipality" value={form.municipality} onChange={(e) => setForm({ ...form, municipality: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
              </div>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("company.deliveries.note")}</Label>
              <Textarea data-testid="company-delivery-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} rows={2} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <div className="flex items-center gap-3 pt-2 border-t border-white/5">
              <Switch data-testid="company-delivery-fromstore" checked={form.fromStore} onCheckedChange={(v) => setForm({ ...form, fromStore: v })} />
              <span className="text-sm">{t("company.deliveries.fromStoreToggle")}</span>
            </div>
            {form.fromStore && (
              <div className="grid grid-cols-1 gap-3 bg-black/20 p-3 border border-white/5">
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.deliveries.product")}</Label>
                  <Select value={form.product_id} onValueChange={(v) => setForm({ ...form, product_id: v })}>
                    <SelectTrigger data-testid="company-delivery-product" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue placeholder={t("company.deliveries.selectPlaceholder")} /></SelectTrigger>
                    <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                      {products.map((p) => <SelectItem key={p.id} value={p.id} data-testid={`company-delivery-product-opt-${p.id}`}>{p.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="micro-label text-neutral-500">{t("company.deliveries.originStore")}</Label>
                    <Select value={form.origin_store_id} onValueChange={(v) => setForm({ ...form, origin_store_id: v })}>
                      <SelectTrigger data-testid="company-delivery-store" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"><SelectValue placeholder={t("company.deliveries.selectPlaceholder")} /></SelectTrigger>
                      <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                        {stores.map((s) => <SelectItem key={s.id} value={s.id} data-testid={`company-delivery-store-opt-${s.id}`}>{s.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="micro-label text-neutral-500">{t("company.deliveries.quantity")}</Label>
                    <Input data-testid="company-delivery-qty" type="number" step="any" min="0" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
                  </div>
                </div>
              </div>
            )}
            <Button data-testid="company-delivery-save" onClick={submit} disabled={busy} className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
              {busy ? t("company.deliveries.saving") : (fee > 0 ? t("company.deliveries.saveBtnWithFee", { fee }) : t("company.deliveries.saveBtn"))}
            </Button>
            {fee > 0 && (
              <p className="text-xs text-neutral-500 text-center">{t("company.deliveries.feeFootnote", { fee })}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
