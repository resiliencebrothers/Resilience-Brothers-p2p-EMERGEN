import { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { API } from "@/App";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import { CalendarClock, Download, Mail, Fingerprint, Loader2 } from "lucide-react";

const MONTHS_ES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

/**
 * iter55.17 — Monthly audit report card.
 *
 * Renders a month/year picker with 3 actions:
 *  - Preview KPIs (auto-triggered on selection change; small text summary)
 *  - Descargar PDF (direct blob download)
 *  - Enviar por email (opens TOTP prompt → POST to backend)
 *
 * Defaults to the previous calendar month (which is the typical audit close).
 */
export default function MonthlyAuditReport() {
  const navigate = useNavigate();
  const now = useMemo(() => new Date(), []);
  const defaultPrev = useMemo(() => {
    // Previous month, with year rollover
    const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    return { year: d.getFullYear(), month: d.getMonth() + 1 };
  }, [now]);

  const [year, setYear] = useState(defaultPrev.year);
  const [month, setMonth] = useState(defaultPrev.month);
  const [summary, setSummary] = useState(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [emailBusy, setEmailBusy] = useState(false);
  const [showTotp, setShowTotp] = useState(false);

  const yearOptions = useMemo(() => {
    const years = [];
    // Cover from 2024 up to current year — audit trail practically started 2026
    for (let y = now.getFullYear(); y >= 2024; y -= 1) years.push(y);
    return years;
  }, [now]);

  const monthOptions = useMemo(() => (
    MONTHS_ES.map((label, idx) => ({ label, value: idx + 1 }))
  ), []);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    setSummary(null);
    try {
      const r = await axios.get(`${API}/admin/audit/monthly.summary`, {
        params: { year, month },
        withCredentials: true,
      });
      setSummary(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Error al cargar resumen mensual");
    } finally {
      setLoadingSummary(false);
    }
  }, [year, month]);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  const downloadPdf = async () => {
    setDownloading(true);
    try {
      const url = `${API}/admin/audit/monthly.pdf?year=${year}&month=${month}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `auditoria-${year}-${String(month).padStart(2, "0")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success("Reporte mensual descargado");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Error al generar el PDF mensual");
    } finally {
      setDownloading(false);
    }
  };

  const sendByEmail = async (totpCode) => {
    setEmailBusy(true);
    try {
      const r = await axios.post(`${API}/admin/audit/monthly/send-email`, {
        year, month, totp_code: totpCode,
      }, { withCredentials: true });
      const { sent, recipients, period_label } = r.data || {};
      toast.success(`Reporte de ${period_label} enviado a ${sent}/${recipients} destinatario(s)`);
      setShowTotp(false);
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e?.response?.data?.detail || "Error al enviar el reporte por email");
      }
    } finally {
      setEmailBusy(false);
    }
  };

  const totalActions = summary?.kpis?.total_actions ?? 0;
  const distinctActors = summary?.kpis?.distinct_actors ?? 0;
  const antiFraud = (summary?.kpis?.anti_fraud || []).reduce((acc, x) => acc + (x.count || 0), 0);
  const emptyMonth = totalActions === 0 && !loadingSummary;

  return (
    <div className="tactile-card p-5 space-y-4" data-testid="audit-monthly-card">
      <div className="flex flex-wrap items-start gap-3 justify-between">
        <div>
          <div className="micro-label text-[#8B5CF6] mb-1 flex items-center gap-2">
            <CalendarClock className="w-3.5 h-3.5" /> Reporte mensual de auditoría
          </div>
          <div className="text-xs text-neutral-400 max-w-xl leading-relaxed">
            Resumen ejecutivo (KPIs por categoría, top actores, señales anti-fraude)
            + tabla detallada + firma SHA-256 para integridad forense. Ideal para
            entregar a compliance o archivar cada cierre de mes.
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="micro-label text-neutral-500 mb-1">Mes</div>
          <Select value={String(month)} onValueChange={(v) => setMonth(Number(v))}>
            <SelectTrigger data-testid="audit-monthly-month" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#141322] border-white/10 text-white rounded-none">
              {monthOptions.map((m) => (
                <SelectItem key={m.value} value={String(m.value)}>{m.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="micro-label text-neutral-500 mb-1">Año</div>
          <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
            <SelectTrigger data-testid="audit-monthly-year" className="rounded-none bg-[#0a0a0a] border-white/10 h-10 w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#141322] border-white/10 text-white rounded-none">
              {yearOptions.map((y) => (
                <SelectItem key={y} value={String(y)}>{y}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-2">
          <Button
            data-testid="audit-monthly-download"
            onClick={downloadPdf}
            disabled={downloading || loadingSummary}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider font-bold disabled:opacity-50"
          >
            {downloading
              ? <><Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" /> Generando...</>
              : <><Download className="w-3.5 h-3.5 mr-2" /> Descargar PDF</>}
          </Button>
          <Button
            data-testid="audit-monthly-email"
            onClick={() => setShowTotp(true)}
            disabled={emailBusy || loadingSummary || emptyMonth}
            title={emptyMonth ? "No hay acciones registradas para enviar" : "Enviar por email al buzón de operaciones"}
            className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 hover:bg-[#8B5CF6]/5 text-white h-10 px-4 font-mono text-xs uppercase tracking-wider disabled:opacity-40"
          >
            <Mail className="w-3.5 h-3.5 mr-2" /> Enviar por email
          </Button>
        </div>
      </div>

      {/* Live KPI preview */}
      <div className="border border-white/10 bg-[#0a0a0a] p-4 space-y-2" data-testid="audit-monthly-summary">
        {loadingSummary && (
          <div className="text-xs text-neutral-500 flex items-center gap-2">
            <Loader2 className="w-3 h-3 animate-spin" /> Calculando resumen...
          </div>
        )}
        {!loadingSummary && summary && (
          <>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <div>
                <div className="micro-label text-neutral-500">Período</div>
                <div className="text-sm text-white font-mono">{summary.period_label}</div>
              </div>
              <div>
                <div className="micro-label text-neutral-500">Acciones</div>
                <div className="text-sm text-white font-mono" data-testid="audit-monthly-count">{totalActions}</div>
              </div>
              <div>
                <div className="micro-label text-neutral-500">Actores</div>
                <div className="text-sm text-white font-mono">{distinctActors}</div>
              </div>
              <div>
                <div className="micro-label text-neutral-500">Anti-fraude</div>
                <div className={`text-sm font-mono ${antiFraud > 0 ? "text-[#EF4444]" : "text-[#22C55E]"}`}>
                  {antiFraud}
                </div>
              </div>
            </div>
            <div className="pt-2 border-t border-white/5 flex items-center gap-2 text-[0.7rem] text-neutral-500 font-mono break-all">
              <Fingerprint className="w-3 h-3 flex-shrink-0 text-[#8B5CF6]" />
              <span className="truncate" title={summary.integrity_hash} data-testid="audit-monthly-hash">
                SHA-256 · {summary.integrity_hash.slice(0, 32)}...
              </span>
            </div>
          </>
        )}
      </div>

      <TotpPromptDialog
        open={showTotp}
        title="Confirmar envío por email"
        description={`Se enviará el reporte de ${MONTHS_ES[month - 1]} ${year} al buzón de operaciones (o a todos los admins). Ingresa tu código 2FA para continuar.`}
        onCancel={() => setShowTotp(false)}
        onConfirm={sendByEmail}
        busy={emailBusy}
      />
    </div>
  );
}
