import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  IdCard, Check, X, Loader2, Clock, CheckCircle2, XCircle, AlertTriangle,
  Info, ShieldAlert, User, Mail, Phone, RefreshCw, Search,
} from "lucide-react";

const STATUS_TABS = [
  { key: "pending", label: "Pendientes", icon: Clock },
  { key: "needs_more_info", label: "Info adicional", icon: Info },
  { key: "verified", label: "Verificados", icon: CheckCircle2 },
  { key: "rejected", label: "Rechazados", icon: XCircle },
];

const REJECT_REASONS = [
  "Foto borrosa",
  "Documento vencido",
  "Selfie no coincide con documento",
  "Documento manipulado / fraude",
  "Nombre no coincide con la cuenta",
  "Documento no válido para este país",
  "Datos incompletos o ilegibles",
];

/**
 * AdminKYC — iter52 identity verification queue.
 * Route: /admin/kyc (staff-only)
 */
export default function AdminKYC() {
  const [tab, setTab] = useState("pending");
  const [items, setItems] = useState([]);
  const [funnel, setFunnel] = useState(null);
  const [search, setSearch] = useState("");
  const [minRisk, setMinRisk] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [action, setAction] = useState(null); // "approve" | "reject" | "more_info"
  const [notes, setNotes] = useState("");
  const [reasons, setReasons] = useState([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [q, f] = await Promise.all([
        axios.get(`${API}/admin/kyc/queue`, {
          params: { status: tab, search: search || undefined, min_risk: minRisk || undefined },
          withCredentials: true,
        }),
        axios.get(`${API}/admin/kyc/funnel`, { withCredentials: true }),
      ]);
      setItems(q.data.items || []);
      setFunnel(f.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo cargar la cola KYC");
    } finally {
      setLoading(false);
    }
  }, [tab, search, minRisk]);

  useEffect(() => { load(); }, [load]);

  const openAction = (v, kind) => {
    setSelected(v);
    setAction(kind);
    setNotes("");
    setReasons([]);
  };

  const submitAction = async () => {
    if (action === "reject" && reasons.length === 0) {
      toast.error("Selecciona al menos un motivo de rechazo.");
      return;
    }
    if (action === "more_info" && notes.trim().length < 5) {
      toast.error("Explica qué información falta (mínimo 5 caracteres).");
      return;
    }
    setSaving(true);
    try {
      const endpoint = action === "more_info" ? "request-more-info" : action;
      const payload = action === "reject"
        ? { reasons, notes: notes.trim() }
        : { notes: notes.trim() };
      await axios.post(`${API}/admin/kyc/${selected.id}/${endpoint}`, payload, { withCredentials: true });
      toast.success(
        action === "approve" ? "Cliente verificado ✓" :
        action === "reject"  ? "Verificación rechazada" :
                               "Se pidió más información al cliente"
      );
      setSelected(null);
      setAction(null);
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo procesar");
    } finally {
      setSaving(false);
    }
  };

  const toggleReason = (r) => {
    setReasons((prev) => prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]);
  };

  return (
    <div className="space-y-6" data-testid="admin-kyc-page">
      {/* HEADER */}
      <header>
        <h1 className="text-3xl font-bold flex items-center gap-3">
          <IdCard className="w-8 h-8 text-[#EAB308]" />
          Verificación de identidad (KYC)
        </h1>
        <p className="text-sm text-neutral-500 mt-1">
          Cola de verificaciones enviadas por clientes. Cada verificación tiene 3 documentos: frente + reverso del documento + selfie.
        </p>
      </header>

      {/* FUNNEL CARDS */}
      {funnel && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <FunnelCard label="Total usuarios" value={funnel.total_users} icon={User} tone="neutral" testid="funnel-total" />
          <FunnelCard label="Pendientes" value={funnel.pending} icon={Clock} tone="warn" testid="funnel-pending" />
          <FunnelCard label="Alto riesgo" value={funnel.high_risk_pending} icon={ShieldAlert} tone="danger" testid="funnel-high-risk" />
          <FunnelCard label="Info adicional" value={funnel.needs_more_info} icon={Info} tone="neutral" testid="funnel-more-info" />
          <FunnelCard label="Verificados" value={funnel.verified} icon={CheckCircle2} tone="ok" testid="funnel-verified" />
          <FunnelCard label="Rechazados" value={funnel.rejected} icon={XCircle} tone="muted" testid="funnel-rejected" />
        </div>
      )}

      {/* CONTROLS */}
      <div className="flex flex-col md:flex-row gap-3 md:items-center">
        <Tabs value={tab} onValueChange={setTab} className="w-full md:w-auto">
          <TabsList className="bg-black/40 border border-white/10">
            {STATUS_TABS.map(({ key, label, icon: Icon }) => (
              <TabsTrigger key={key} value={key} data-testid={`kyc-tab-${key}`} className="data-[state=active]:bg-[#EAB308] data-[state=active]:text-black text-xs">
                <Icon className="w-3.5 h-3.5 mr-1.5" /> {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="relative flex-1 md:max-w-xs ml-auto">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
          <Input
            data-testid="kyc-search-input"
            placeholder="Buscar por nombre / email / phone…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-black/40 border-white/10 text-white text-sm"
          />
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-neutral-500 whitespace-nowrap">Riesgo min:</label>
          <Input
            type="number"
            min={0}
            max={100}
            value={minRisk}
            onChange={(e) => setMinRisk(parseInt(e.target.value || "0", 10))}
            className="w-16 bg-black/40 border-white/10 text-white text-xs text-center"
            data-testid="kyc-min-risk-input"
          />
        </div>

        <Button
          data-testid="kyc-refresh-btn"
          onClick={load}
          size="sm"
          variant="outline"
          className="border-white/10 text-neutral-300 hover:bg-white/5"
        >
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Recargar
        </Button>
      </div>

      {/* LIST */}
      {loading && <div className="text-neutral-500 text-sm">Cargando…</div>}
      {!loading && items.length === 0 && (
        <div className="text-center py-12 text-neutral-500 border border-white/5 bg-black/30">
          No hay verificaciones {tab === "pending" ? "pendientes" : `en estado "${tab}"`}. ✅
        </div>
      )}
      {!loading && items.length > 0 && (
        <div className="space-y-2" data-testid="kyc-list">
          {items.map((v) => (
            <VerificationRow key={v.id} v={v} onAction={openAction} />
          ))}
        </div>
      )}

      {/* ACTION DIALOG */}
      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="bg-neutral-950 border-white/10 max-w-2xl" data-testid="kyc-action-dialog">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="text-white flex items-center gap-2">
                  {action === "approve" && <><CheckCircle2 className="w-5 h-5 text-emerald-400" /> Aprobar verificación</>}
                  {action === "reject" && <><XCircle className="w-5 h-5 text-[#EF4444]" /> Rechazar verificación</>}
                  {action === "more_info" && <><Info className="w-5 h-5 text-[#EAB308]" /> Pedir más información</>}
                </DialogTitle>
                <DialogDescription className="text-neutral-500">
                  Cliente: <span className="text-white">{selected.user_name}</span> · {selected.user_email}
                </DialogDescription>
              </DialogHeader>

              {/* Documents preview */}
              <div className="grid grid-cols-3 gap-2">
                {selected.documents?.map((d) => (
                  <div key={d.doc_type} className="border border-white/10 bg-black/40 p-2">
                    <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500 mb-1">
                      {d.doc_type.replace("_", " ")}
                    </div>
                    <a href={d.ref} target="_blank" rel="noreferrer" className="block">
                      <img
                        src={d.ref}
                        alt={d.doc_type}
                        className="w-full h-32 object-cover border border-white/10 hover:opacity-80 transition"
                        data-testid={`kyc-doc-${d.doc_type}`}
                      />
                    </a>
                  </div>
                ))}
              </div>

              {/* Risk flags */}
              {selected.risk_flags?.length > 0 && (
                <div className="border border-amber-500/30 bg-amber-500/5 p-3 space-y-1">
                  <div className="text-xs font-semibold text-amber-300 flex items-center gap-1.5">
                    <AlertTriangle className="w-4 h-4" /> Riesgo: {selected.risk_score}/100
                  </div>
                  {selected.risk_flags.map((f) => (
                    <div key={f.code} className="text-[0.7rem] text-amber-200">
                      • [{f.severity}] {f.message}
                    </div>
                  ))}
                </div>
              )}

              {/* Reject reasons checklist */}
              {action === "reject" && (
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wider text-neutral-500">Motivos (selecciona ≥ 1)</label>
                  {REJECT_REASONS.map((r) => (
                    <label key={r} className="flex items-center gap-2 text-sm text-neutral-200 cursor-pointer">
                      <Checkbox
                        data-testid={`kyc-reject-reason-${r.replace(/\s/g, '-').toLowerCase()}`}
                        checked={reasons.includes(r)}
                        onCheckedChange={() => toggleReason(r)}
                      />
                      {r}
                    </label>
                  ))}
                </div>
              )}

              <div>
                <label className="text-xs uppercase tracking-wider text-neutral-500">
                  {action === "more_info" ? "Explica qué necesitas del cliente" : "Notas internas (opcional)"}
                </label>
                <Textarea
                  data-testid="kyc-action-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  placeholder={
                    action === "more_info"
                      ? "Ej: La foto del reverso salió cortada, vuelve a subirla con mejor luz."
                      : ""
                  }
                  className="bg-black/40 border-white/10 text-white text-sm mt-1"
                />
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setSelected(null)} className="border-white/10 text-neutral-300 hover:bg-white/5">
                  Cancelar
                </Button>
                <Button
                  data-testid="kyc-action-submit"
                  onClick={submitAction}
                  disabled={saving}
                  className={
                    action === "approve" ? "bg-emerald-500 text-black hover:bg-emerald-500/90" :
                    action === "reject" ? "bg-[#EF4444] text-white hover:bg-[#EF4444]/90" :
                    "bg-[#EAB308] text-black hover:bg-[#EAB308]/90"
                  }
                >
                  {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                  Confirmar
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function FunnelCard({ label, value, icon: Icon, tone, testid }) {
  const toneClasses = {
    neutral: "border-white/10 bg-black/30 text-white",
    warn: "border-[#EAB308]/40 bg-[#EAB308]/5 text-[#FEF3C7]",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
    ok: "border-emerald-500/40 bg-emerald-500/5 text-emerald-200",
    muted: "border-white/5 bg-black/20 text-neutral-400",
  };
  return (
    <div className={`border ${toneClasses[tone]} p-3`} data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[0.65rem] uppercase tracking-wider opacity-70">{label}</span>
        <Icon className="w-4 h-4 opacity-60" />
      </div>
      <div className="text-2xl font-bold">{value ?? 0}</div>
    </div>
  );
}

function VerificationRow({ v, onAction }) {
  const statusStyle = {
    pending: "border-[#EAB308]/40 bg-[#EAB308]/5",
    needs_more_info: "border-blue-500/40 bg-blue-500/5",
    verified: "border-emerald-500/40 bg-emerald-500/5",
    rejected: "border-neutral-500/30 bg-neutral-500/5",
  }[v.status];
  const riskColor = v.risk_score >= 60 ? "text-[#EF4444]" : v.risk_score >= 30 ? "text-[#EAB308]" : "text-emerald-400";

  return (
    <div className={`border ${statusStyle} p-4`} data-testid={`kyc-row-${v.id}`}>
      <div className="flex flex-col md:flex-row md:items-start gap-3">
        <div className="flex-1 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-white flex items-center gap-1.5">
              <User className="w-4 h-4 text-neutral-500" /> {v.user_name}
            </div>
            <span className={`text-xs font-mono ${riskColor}`}>Riesgo {v.risk_score}/100</span>
            {v.risk_flags?.length > 0 && (
              <span className="text-[0.65rem] text-amber-300 uppercase">
                <AlertTriangle className="inline w-3 h-3 mr-0.5" /> {v.risk_flags.length} señal(es)
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-neutral-400">
            <span className="flex items-center gap-1"><Mail className="w-3 h-3" /> {v.user_email}</span>
            <span className="flex items-center gap-1"><Phone className="w-3 h-3" /> {v.user_phone || "—"}</span>
            <span className="text-neutral-500">Enviado: {v.created_at?.slice(0, 16).replace("T", " ")}</span>
          </div>
          {v.risk_flags?.length > 0 && (
            <ul className="text-[0.7rem] text-amber-200/80 mt-1 space-y-0.5">
              {v.risk_flags.slice(0, 3).map((f) => (
                <li key={f.code}>• {f.message}</li>
              ))}
            </ul>
          )}
          {v.status === "rejected" && v.rejection_reasons?.length > 0 && (
            <div className="text-[0.7rem] text-neutral-400">
              Rechazado: {v.rejection_reasons.join(" · ")}
            </div>
          )}
          {v.review_notes && (
            <div className="text-[0.7rem] text-neutral-400 italic">
              Nota: {v.review_notes}
            </div>
          )}
        </div>

        {(v.status === "pending" || v.status === "needs_more_info") && (
          <div className="flex flex-wrap gap-2">
            <Button
              data-testid={`kyc-approve-btn-${v.id}`}
              size="sm"
              onClick={() => onAction(v, "approve")}
              className="bg-emerald-500 text-black hover:bg-emerald-500/90 h-8"
            >
              <Check className="w-3.5 h-3.5 mr-1" /> Aprobar
            </Button>
            <Button
              data-testid={`kyc-more-info-btn-${v.id}`}
              size="sm"
              variant="outline"
              onClick={() => onAction(v, "more_info")}
              className="border-[#EAB308]/40 text-[#EAB308] hover:bg-[#EAB308]/10 h-8"
            >
              <Info className="w-3.5 h-3.5 mr-1" /> Más info
            </Button>
            <Button
              data-testid={`kyc-reject-btn-${v.id}`}
              size="sm"
              variant="outline"
              onClick={() => onAction(v, "reject")}
              className="border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8"
            >
              <X className="w-3.5 h-3.5 mr-1" /> Rechazar
            </Button>
          </div>
        )}
        {v.status === "verified" && (
          <div className="text-emerald-400 text-xs font-semibold flex items-center gap-1">
            <CheckCircle2 className="w-4 h-4" /> Verificado
          </div>
        )}
        {v.status === "rejected" && (
          <div className="text-[#EF4444] text-xs font-semibold flex items-center gap-1">
            <XCircle className="w-4 h-4" /> Rechazado
          </div>
        )}
      </div>
    </div>
  );
}
