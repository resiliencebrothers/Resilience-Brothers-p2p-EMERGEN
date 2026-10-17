import { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  Building2, Upload, Check, X, Loader2, FileImage, FileText, ShieldCheck,
  AlertTriangle, Info, RefreshCw, ArrowRight,
} from "lucide-react";

// Verificación de cuenta Empresa: código fiscal, licencia operativa y
// dirección legal (en vez del documento de identidad personal + selfie).
// Reusa /kyc/my-status para el estado y POSTea a /kyc/company/submit.
const DOC_STEPS = [
  { key: "tax_certificate", label: "Código / certificado fiscal", hint: "Foto, escaneo o PDF del documento que acredita tu código fiscal." },
  { key: "operating_license", label: "Licencia operativa", hint: "Foto, escaneo o PDF de la licencia que autoriza tu actividad comercial." },
  { key: "legal_rep_id", label: "ID del representante legal", hint: "Foto, escaneo o PDF del documento de identidad del representante legal de la empresa." },
];

const STATUS_META = {
  unverified:      { label: "Sin verificar", tone: "muted",  icon: Info },
  pending:         { label: "En revisión",   tone: "warn",   icon: Loader2 },
  needs_more_info: { label: "Requiere más información", tone: "warn", icon: AlertTriangle },
  verified:        { label: "Verificada",    tone: "ok",     icon: ShieldCheck },
  rejected:        { label: "Rechazada",     tone: "danger", icon: X },
  superseded:      { label: "Reemplazada",   tone: "muted",  icon: Info },
};

export default function CompanyKYCView() {
  const { user } = useAuth();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reverify, setReverify] = useState(false);
  const [fiscalCode, setFiscalCode] = useState("");
  const [legalAddress, setLegalAddress] = useState("");
  const [companyName, setCompanyName] = useState(user?.name || "");
  const [docs, setDocs] = useState({ tax_certificate: null, operating_license: null, legal_rep_id: null });
  const fileRefs = { tax_certificate: useRef(), operating_license: useRef(), legal_rep_id: useRef() };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/kyc/my-status`, { withCredentials: true });
      setStatus(r.data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo cargar tu estado de verificación");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleFile = (docKey, ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) { toast.error("Archivo muy grande (máximo 8 MB)."); return; }
    const isImg = file.type.startsWith("image/");
    const isPdf = file.type === "application/pdf";
    if (!isImg && !isPdf) { toast.error("Solo se aceptan imágenes (JPG, PNG) o PDF."); return; }
    const reader = new FileReader();
    reader.onload = () => setDocs((p) => ({ ...p, [docKey]: { data: reader.result, name: file.name, isPdf } }));
    reader.readAsDataURL(file);
  };

  const removeFile = (docKey) => {
    setDocs((p) => ({ ...p, [docKey]: null }));
    if (fileRefs[docKey].current) fileRefs[docKey].current.value = "";
  };

  const allReady = fiscalCode.trim() && legalAddress.trim()
    && docs.tax_certificate && docs.operating_license && docs.legal_rep_id;

  const submit = async () => {
    if (!allReady) { toast.error("Completa el código fiscal, la dirección y sube los tres documentos."); return; }
    setSubmitting(true);
    try {
      await axios.post(`${API}/kyc/company/submit`, {
        fiscal_code: fiscalCode.trim(),
        legal_address: legalAddress.trim(),
        company_name: companyName.trim(),
        tax_certificate: docs.tax_certificate.data,
        operating_license: docs.operating_license.data,
        legal_rep_id: docs.legal_rep_id.data,
      }, { withCredentials: true });
      toast.success("Verificación enviada. El equipo la revisará pronto.");
      setDocs({ tax_certificate: null, operating_license: null, legal_rep_id: null });
      setReverify(false);
      for (const k of Object.keys(fileRefs)) { if (fileRefs[k].current) fileRefs[k].current.value = ""; }
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo enviar la verificación.");
    } finally {
      setSubmitting(false);
    }
  };

  const s = status?.status || "unverified";
  const v = status?.verification;
  // R05 — needs_more_info permite subsanar; R10 — 'superseded' (expediente
  // huérfano por un fallo de reemplazo) también puede reenviarse para recuperar.
  const canSubmit = s === "unverified" || s === "rejected"
    || s === "needs_more_info" || s === "superseded"
    || (s === "verified" && reverify);
  const cfg = STATUS_META[s] || STATUS_META.unverified;
  const StatusIcon = cfg.icon;
  const toneCls = {
    muted: "border-white/10 bg-black/30 text-neutral-300",
    warn: "border-[#8B5CF6]/40 bg-[#8B5CF6]/5 text-[#FEF3C7]",
    ok: "border-emerald-500/40 bg-emerald-500/5 text-emerald-200",
    danger: "border-[#EF4444]/40 bg-[#EF4444]/5 text-[#FEE2E2]",
  }[cfg.tone];

  return (
    <div className="max-w-3xl space-y-6" data-testid="company-kyc-page">
      <header>
        <h1 className="text-3xl font-bold text-white flex items-center gap-3">
          <Building2 className="w-7 h-7 text-[#8B5CF6]" /> Verificación de empresa
        </h1>
        <p className="text-neutral-500 text-sm mt-2">
          Presenta tu código fiscal, tu licencia operativa y tu dirección legal.
          La revisión habilita los retiros de tu cuenta.
        </p>
      </header>

      {loading && <div className="text-neutral-500 text-sm">Cargando tu estado…</div>}

      {!loading && status && (
        <>
          <div className={`border ${toneCls} p-4 flex items-center gap-3`} data-testid="company-kyc-status-card">
            <StatusIcon className={`w-6 h-6 ${s === "pending" ? "animate-spin" : ""}`} />
            <div>
              <div className="text-sm font-semibold">{cfg.label}</div>
              {v?.created_at && (
                <div className="text-xs opacity-70">Enviado: {v.created_at.slice(0, 16).replace("T", " ")}</div>
              )}
            </div>
          </div>

          {s === "rejected" && v?.rejection_reasons?.length > 0 && (
            <div className="border border-[#EF4444]/30 bg-[#EF4444]/5 p-4" data-testid="company-kyc-rejection">
              <div className="text-sm font-semibold text-[#FEE2E2] flex items-center gap-2 mb-2">
                <X className="w-4 h-4" /> Motivos del rechazo
              </div>
              <ul className="text-xs text-neutral-300 space-y-1 list-disc pl-5">
                {v.rejection_reasons.map((r) => (<li key={r}>{r}</li>))}
              </ul>
              {v.review_notes && <div className="text-xs text-neutral-400 italic mt-2">Nota del equipo: {v.review_notes}</div>}
            </div>
          )}

          {s === "needs_more_info" && v?.review_notes && (
            <div className="border border-blue-500/30 bg-blue-500/5 p-4" data-testid="company-kyc-more-info">
              <div className="text-sm font-semibold text-blue-200 flex items-center gap-2 mb-2">
                <Info className="w-4 h-4" /> Información adicional requerida
              </div>
              <div className="text-xs text-neutral-300">{v.review_notes}</div>
            </div>
          )}

          {canSubmit && (
            <div className="space-y-4">
              {s === "verified" && reverify && (
                <div className="border border-amber-500/40 bg-amber-500/5 p-4 text-xs text-amber-200" data-testid="company-kyc-revalidation-notice">
                  Estás actualizando una verificación ya aprobada. Al reenviarla,
                  tu empresa vuelve a <strong>revisión</strong> y los retiros se
                  pausan hasta que el equipo apruebe la nueva versión.
                </div>
              )}
              <div className="grid sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wider text-neutral-500">Nombre de la empresa</label>
                  <Input
                    data-testid="company-kyc-name"
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    placeholder="Razón social"
                    className="bg-black/40 border-white/10 text-white"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs uppercase tracking-wider text-neutral-500">Código fiscal *</label>
                  <Input
                    data-testid="company-kyc-fiscal-code"
                    value={fiscalCode}
                    onChange={(e) => setFiscalCode(e.target.value)}
                    placeholder="Número de identificación fiscal"
                    className="bg-black/40 border-white/10 text-white font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs uppercase tracking-wider text-neutral-500">Dirección legal *</label>
                <Textarea
                  data-testid="company-kyc-address"
                  value={legalAddress}
                  onChange={(e) => setLegalAddress(e.target.value)}
                  rows={2}
                  placeholder="Calle, número, municipio, provincia"
                  className="bg-black/40 border-white/10 text-white"
                />
              </div>

              <h2 className="text-lg font-semibold text-white pt-2">Documentos</h2>
              {DOC_STEPS.map(({ key, label, hint }) => (
                <div key={key} className="border border-white/10 bg-black/30 p-4" data-testid={`company-kyc-upload-${key}`}>
                  <div className="flex items-start gap-3">
                    <div className="flex-1 space-y-1">
                      <div className="text-sm font-semibold text-white flex items-center gap-2">
                        <FileImage className="w-4 h-4 text-[#8B5CF6]" /> {label} *
                      </div>
                      <div className="text-xs text-neutral-500">{hint}</div>
                    </div>
                    {docs[key] ? (
                      <div className="flex items-center gap-2">
                        {docs[key].isPdf ? (
                          <span className="flex items-center gap-1.5 px-2 py-2 border border-white/10 bg-black/40 text-xs text-neutral-200 max-w-[10rem] truncate" title={docs[key].name}>
                            <FileText className="w-4 h-4 text-[#8B5CF6] shrink-0" /> {docs[key].name}
                          </span>
                        ) : (
                          <img src={docs[key].data} alt={label} className="w-20 h-20 object-cover border border-white/10" />
                        )}
                        <Button size="sm" variant="outline" onClick={() => removeFile(key)}
                          className="border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 h-8"
                          data-testid={`company-kyc-remove-${key}`}>
                          <X className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <label className="cursor-pointer">
                        <input ref={fileRefs[key]} type="file" accept="image/*,application/pdf"
                          onChange={(e) => handleFile(key, e)} className="hidden"
                          data-testid={`company-kyc-file-input-${key}`} />
                        <span className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6] text-xs font-semibold hover:bg-[#8B5CF6]/20 transition">
                          <Upload className="w-3.5 h-3.5" /> Elegir archivo
                        </span>
                      </label>
                    )}
                  </div>
                  {docs[key] && (
                    <div className="text-[0.65rem] text-emerald-400 mt-2 flex items-center gap-1">
                      <Check className="w-3 h-3" /> Listo para enviar
                    </div>
                  )}
                </div>
              ))}

              <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-2">
                <Button
                  data-testid="company-kyc-submit-btn"
                  onClick={submit}
                  disabled={!allReady || submitting}
                  className="bg-[#8B5CF6] text-white hover:bg-[#8B5CF6]/90 disabled:opacity-40">
                  {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                  {submitting ? "Enviando…" : "Enviar verificación"}
                  {!submitting && <ArrowRight className="w-4 h-4 ml-2" />}
                </Button>
                <p className="text-xs text-neutral-500">El equipo suele responder en menos de 48 h.</p>
                {s === "verified" && reverify && (
                  <Button variant="ghost" size="sm" onClick={() => { setReverify(false); removeFile("tax_certificate"); removeFile("operating_license"); removeFile("legal_rep_id"); }}
                    className="text-neutral-400 hover:text-white"
                    data-testid="company-kyc-cancel-reverify-btn">
                    Cancelar
                  </Button>
                )}
              </div>
            </div>
          )}

          {(s === "pending" || (s === "verified" && !reverify)) && (
            <div className="border border-white/10 bg-black/30 p-6 text-sm text-neutral-400" data-testid="company-kyc-settled">
              {s === "pending" && "Tu verificación está en revisión. Te avisaremos cuando haya una decisión."}
              {s === "verified" && "Tu empresa está verificada. Ya puedes solicitar retiros."}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={load}
                  className="border-white/10 text-neutral-300 hover:bg-white/5"
                  data-testid="company-kyc-refresh-btn">
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Actualizar estado
                </Button>
                {s === "verified" && (
                  <Button variant="outline" size="sm" onClick={() => setReverify(true)}
                    className="border-[#8B5CF6]/40 text-[#8B5CF6] hover:bg-[#8B5CF6]/10"
                    data-testid="company-kyc-reverify-btn">
                    <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Actualizar datos / re-verificar
                  </Button>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
