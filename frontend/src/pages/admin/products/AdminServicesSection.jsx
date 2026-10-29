import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Wrench, Check, X, Plus, Trash2, Tags, MapPin } from "lucide-react";
import { toast } from "sonner";

// Cola de aprobación de SERVICIOS de Empresas + gestor de categorías. Mismo
// permiso que productos ('products'), reutiliza la página admin de Productos.
const WD = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MODALITY = { local: "En local", domicilio: "A domicilio", remoto: "Remoto", alquiler: "Alquiler" };
const STATUS_BADGE = {
  draft: "bg-neutral-500/10 text-neutral-300 border-neutral-500/30",
  pending: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  published: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border-red-500/30",
  paused: "bg-sky-500/10 text-sky-300 border-sky-500/30",
};
const STATUS_LABEL = { draft: "Borrador", pending: "Pendiente", published: "Publicado", rejected: "Rechazado", paused: "Pausado" };
const effStatus = (s) => (s.status === "published" && !s.is_active ? "paused" : s.status);
const canApprove = (s) => s.status === "pending" || s.status === "rejected";
const canReject = (s) => s.status === "pending" || s.status === "published";

const priceText = (s) => {
  if (s.pricing_type === "quote") return "A presupuestar";
  const unit = { hourly: "/hora", daily: "/día", per_person: "/persona" }[s.pricing_type] || "";
  return `${s.price_usdt} USDT${unit}`;
};

export default function AdminServicesSection() {
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState(false);
  const [cats, setCats] = useState([]);
  const [newCat, setNewCat] = useState("");

  const load = useCallback(() => {
    const params = statusFilter === "all" ? {} : { status: statusFilter };
    axios.get(`${API}/admin/services`, { params, withCredentials: true })
      .then((r) => setItems(r.data)).catch(() => {});
  }, [statusFilter]);

  const loadCats = useCallback(() => {
    axios.get(`${API}/admin/service-categories`, { withCredentials: true })
      .then((r) => setCats(r.data)).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadCats(); }, [loadCats]);

  const catName = (slug) => cats.find((c) => c.slug === slug)?.name || slug;

  const approve = async (s) => {
    try {
      await axios.post(`${API}/admin/services/${s.id}/approve`, {}, { withCredentials: true });
      toast.success("Servicio publicado");
      setDetail(null); load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const reject = async () => {
    if (!rejecting) return;
    setBusy(true);
    try {
      await axios.post(`${API}/admin/services/${rejecting.id}/reject`, { reason }, { withCredentials: true });
      toast.success("Servicio rechazado");
      setRejecting(null); setReason(""); setDetail(null); load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const addCategory = async () => {
    if (!newCat.trim()) return;
    try {
      await axios.post(`${API}/admin/service-categories`, { name: newCat.trim(), active: true }, { withCredentials: true });
      toast.success("Categoría creada"); setNewCat(""); loadCats();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const toggleCategory = async (c) => {
    try {
      await axios.put(`${API}/admin/service-categories/${c.id}`, { name: c.name, active: !c.active }, { withCredentials: true });
      loadCats();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const deleteCategory = async (c) => {
    if (!window.confirm(`¿Eliminar la categoría «${c.name}»?`)) return;
    try {
      const r = await axios.delete(`${API}/admin/service-categories/${c.id}`, { withCredentials: true });
      toast.success(r.data?.deactivated ? "Categoría en uso: se desactivó" : "Categoría eliminada");
      loadCats();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const statusTabs = ["pending", "published", "rejected", "draft", "all"];

  return (
    <div className="mt-12" data-testid="admin-services-section">
      <h2 className="font-display text-xl flex items-center gap-2 mb-4">
        <Wrench className="w-5 h-5 text-[#8B5CF6]" /> Servicios de empresas
      </h2>

      <div className="flex gap-2 mb-4 flex-wrap">
        {statusTabs.map((s) => (
          <button key={s} data-testid={`admin-services-filter-${s}`} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 text-xs uppercase tracking-wider border transition-colors ${statusFilter === s ? "border-[#8B5CF6] text-[#8B5CF6] bg-[#8B5CF6]/10" : "border-white/10 text-neutral-400 hover:text-white"}`}>
            {s === "all" ? "Todos" : STATUS_LABEL[s]}
          </button>
        ))}
      </div>

      {items.length === 0 && (
        <p className="text-neutral-500 text-sm py-6 text-center tactile-card" data-testid="admin-services-empty">
          No hay servicios en este estado.
        </p>
      )}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((s) => (
          <div key={s.id} className="tactile-card overflow-hidden flex flex-col" data-testid={`admin-service-${s.id}`}>
            <div className="aspect-video bg-[#0a0a0a]">
              {s.images?.[0] ? <img src={s.images[0]} alt={s.title} className="w-full h-full object-cover" />
                : <div className="w-full h-full flex items-center justify-center"><Wrench className="w-10 h-10 text-neutral-700" /></div>}
            </div>
            <div className="p-4 flex-1 flex flex-col">
              <div className="flex items-center justify-between gap-2">
                <div className="micro-label text-neutral-500">{catName(s.category)}</div>
                <span className={`text-[0.6rem] uppercase tracking-wider px-2 py-0.5 border ${STATUS_BADGE[effStatus(s)] || ""}`}>{STATUS_LABEL[effStatus(s)]}</span>
              </div>
              <h3 className="font-display text-lg mt-1">{s.title}</h3>
              <div className="text-xs text-[#A78BFA] mt-1">{s.owner_name}</div>
              <div className="text-xs text-neutral-500 mt-1 flex items-center gap-1"><MapPin className="w-3 h-3" /> {MODALITY[s.modality]}{s.coverage_zone ? ` · ${s.coverage_zone}` : ""}</div>
              {s.status === "rejected" && s.rejection_reason && <div className="text-xs text-red-400 mt-1">{s.rejection_reason}</div>}
              <div className="mt-auto pt-3 flex items-center justify-between">
                <div className="font-display text-lg text-[#8B5CF6]">{priceText(s)}</div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" data-testid={`admin-service-view-${s.id}`} onClick={() => setDetail(s)}
                    className="border-white/15 text-neutral-200 hover:text-white rounded-none h-8">Ver</Button>
                  {canApprove(s) && (
                    <Button size="sm" data-testid={`admin-service-approve-${s.id}`} onClick={() => approve(s)}
                      className="bg-emerald-600 hover:bg-emerald-500 text-white rounded-none h-8"><Check className="w-4 h-4" /></Button>
                  )}
                  {canReject(s) && (
                    <Button size="sm" variant="outline" data-testid={`admin-service-reject-${s.id}`} onClick={() => { setRejecting(s); setReason(""); }}
                      className="border-red-500/40 text-red-400 hover:bg-red-500/10 rounded-none h-8"><X className="w-4 h-4" /></Button>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Gestor de categorías */}
      <div className="mt-10" data-testid="admin-service-categories">
        <h3 className="font-display text-lg flex items-center gap-2 mb-3"><Tags className="w-5 h-5 text-[#8B5CF6]" /> Categorías de servicios</h3>
        <div className="flex items-center gap-2 mb-3">
          <Input data-testid="admin-service-cat-input" value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="Nueva categoría" className="rounded-none bg-[#0a0a0a] border-white/10 h-9 w-[220px]" />
          <Button data-testid="admin-service-cat-add" onClick={addCategory} className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9"><Plus className="w-4 h-4 mr-1" /> Añadir</Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {cats.map((c) => (
            <div key={c.id} data-testid={`admin-service-cat-${c.slug}`} className={`inline-flex items-center gap-2 px-3 py-1.5 border text-sm ${c.active ? "border-white/15 text-neutral-200" : "border-white/10 text-neutral-500"}`}>
              <span>{c.name}</span>
              <Switch data-testid={`admin-service-cat-toggle-${c.slug}`} checked={c.active} onCheckedChange={() => toggleCategory(c)} className="scale-75" />
              <button data-testid={`admin-service-cat-delete-${c.slug}`} onClick={() => deleteCategory(c)} className="text-neutral-500 hover:text-[#EF4444]"><Trash2 className="w-3.5 h-3.5" /></button>
            </div>
          ))}
        </div>
      </div>

      {/* Detalle del servicio */}
      <Dialog open={!!detail} onOpenChange={(v) => !v && setDetail(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[88vh] overflow-y-auto sm:max-w-xl" data-testid="admin-service-detail">
          {detail && (
            <>
              <DialogHeader><DialogTitle className="font-display">{detail.title}</DialogTitle></DialogHeader>
              <div className="space-y-3">
                {detail.images?.[0] && <img src={detail.images[0]} alt={detail.title} className="w-full aspect-video object-cover border border-white/10" />}
                <div className="text-sm text-neutral-400">{catName(detail.category)} · {MODALITY[detail.modality]} · {priceText(detail)}</div>
                <div className="text-sm text-neutral-300">Empresa: {detail.owner_name}{detail.coverage_zone ? ` · ${detail.coverage_zone}` : ""}</div>
                {detail.description && <p className="text-sm text-neutral-300 whitespace-pre-line">{detail.description}</p>}
                <div className="text-sm text-neutral-300">
                  {detail.duration_minutes > 0 && <div>Duración: {detail.duration_minutes} min</div>}
                  {detail.capacity > 1 && <div>Cupos: {detail.capacity}</div>}
                  {detail.deposit_type && detail.deposit_type !== "none" && detail.deposit_value > 0 && (
                    <div>Anticipo: {detail.deposit_type === "percent" ? `${detail.deposit_value}%` : `${detail.deposit_value} USDT`}</div>
                  )}
                  <div>Pago: {(detail.payment_methods || []).map((m) => (m === "balance" ? "Saldo USDT" : "Efectivo")).join(" · ") || "Saldo USDT"}</div>
                </div>
                {detail.availability?.length > 0 && (
                  <div><div className="micro-label text-neutral-500 mb-1">Disponibilidad</div>
                    <ul className="text-sm text-neutral-300 space-y-0.5">{detail.availability.map((w, i) => <li key={i}>{WD[w.day]}: {w.start}–{w.end}</li>)}</ul>
                  </div>
                )}
                {detail.inclusions && <div><div className="micro-label text-neutral-500 mb-1">Incluye</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.inclusions}</p></div>}
                {detail.requirements && <div><div className="micro-label text-neutral-500 mb-1">Requisitos</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.requirements}</p></div>}
                {detail.cancellation_policy && <div><div className="micro-label text-neutral-500 mb-1">Cancelación</div><p className="text-sm text-neutral-300 whitespace-pre-line">{detail.cancellation_policy}</p></div>}
                <div className="flex gap-2 pt-2">
                  {canApprove(detail) && (
                    <Button data-testid="admin-service-detail-approve" onClick={() => approve(detail)} className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-none h-10"><Check className="w-4 h-4 mr-1" /> Aprobar</Button>
                  )}
                  {canReject(detail) && (
                    <Button data-testid="admin-service-detail-reject" variant="outline" onClick={() => { setRejecting(detail); setReason(""); }} className="flex-1 border-red-500/40 text-red-400 hover:bg-red-500/10 rounded-none h-10"><X className="w-4 h-4 mr-1" /> Rechazar</Button>
                  )}
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!rejecting} onOpenChange={() => setRejecting(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">Rechazar: {rejecting?.title}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="micro-label text-neutral-500">Motivo (se envía a la empresa)</Label>
              <Input data-testid="admin-service-reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
            </div>
            <Button data-testid="admin-service-reject-confirm" onClick={reject} disabled={busy} className="w-full bg-red-600 hover:bg-red-500 text-white rounded-none">Rechazar</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
