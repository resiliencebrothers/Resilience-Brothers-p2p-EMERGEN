import { useEffect, useState, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Turnstile } from "@marsidev/react-turnstile";
import { getTheme } from "@/lib/theme";
import { toast } from "sonner";
import {
  Building2, Clock, ShieldCheck, XCircle, Mail, Loader2, Search, Send,
} from "lucide-react";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const STATUS_UI = {
  pending: {
    icon: Clock, color: "#EAB308", title: "En revisión",
    text: "El equipo está revisando tu solicitud de cuenta Empresa. Te avisaremos por correo en cuanto haya una decisión.",
  },
  approved_unverified: {
    icon: Mail, color: "#8B5CF6", title: "Aprobada — verifica tu correo",
    text: "¡Buenas noticias! Tu solicitud fue aprobada. Revisa tu correo y pulsa el enlace de verificación para activar tu cuenta y empezar a operar.",
  },
  approved_verified: {
    icon: ShieldCheck, color: "#22C55E", title: "Aprobada y activa",
    text: "Tu cuenta Empresa está lista. Ya puedes iniciar sesión y operar.",
  },
  rejected: {
    icon: XCircle, color: "#EF4444", title: "Rechazada",
    text: "Tu solicitud no pudo aprobarse. Revisa tu correo: incluimos un enlace para reenviar tu documentación corregida en un clic.",
  },
};

function StatusCard({ data }) {
  let key = data.status;
  if (data.status === "approved") key = data.email_verified ? "approved_verified" : "approved_unverified";
  const ui = STATUS_UI[key] || STATUS_UI.pending;
  const Icon = ui.icon;
  return (
    <div className="tactile-card p-8 max-w-md w-full text-center" data-testid="company-status-card">
      <Icon className="w-12 h-12 mx-auto mb-4" style={{ color: ui.color }} data-testid="company-status-icon" />
      <div className="micro-label text-neutral-500 mb-1">{data.company_name || "Tu solicitud"}</div>
      <h1 className="font-display text-2xl mb-3" data-testid="company-status-title" style={{ color: ui.color }}>
        {ui.title}
      </h1>
      <p className="text-neutral-400 text-sm leading-relaxed mb-4" data-testid="company-status-text">{ui.text}</p>
      {data.status === "rejected" && data.rejection_reason && (
        <div className="border border-[#EF4444]/40 bg-[#EF4444]/5 p-3 text-left mb-4" data-testid="company-status-reason">
          <div className="micro-label text-[#EF4444] mb-1">Motivo</div>
          <p className="text-sm text-neutral-200 whitespace-pre-line">{data.rejection_reason}</p>
        </div>
      )}
      <Link to="/" className="text-[#8B5CF6] hover:underline text-sm" data-testid="company-status-home-link">
        ← Volver al inicio
      </Link>
    </div>
  );
}

function RequestLinkForm() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [captchaCfg, setCaptchaCfg] = useState(null);
  const [captchaToken, setCaptchaToken] = useState("");
  const [captchaKey, setCaptchaKey] = useState(0);
  const didLoad = useRef(false);

  useEffect(() => {
    if (didLoad.current) return;
    didLoad.current = true;
    axios.get(`${API}/captcha/config`).then((r) => setCaptchaCfg(r.data)).catch(() => setCaptchaCfg({ enabled: false }));
  }, []);

  const captchaMissing = captchaCfg?.enforced && !captchaToken;
  const canSend = EMAIL_RE.test(email.trim()) && !sending && !captchaMissing;

  const submit = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      const r = await axios.post(`${API}/company-signup/status-link`, {
        email: email.trim().toLowerCase(),
        ...(captchaCfg?.enabled && captchaToken ? { captcha_token: captchaToken } : {}),
      });
      toast.success(r.data?.message || "Enlace enviado si existe una solicitud.");
      setSent(true);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "No se pudo enviar el enlace.");
      setCaptchaToken("");
      setCaptchaKey((k) => k + 1);
    } finally {
      setSending(false);
    }
  };

  if (sent) {
    return (
      <div className="tactile-card p-8 max-w-md w-full text-center" data-testid="company-status-link-sent">
        <Mail className="w-12 h-12 text-[#8B5CF6] mx-auto mb-4" />
        <h1 className="font-display text-2xl mb-3">Revisa tu correo</h1>
        <p className="text-neutral-400 text-sm leading-relaxed mb-4">
          Si existe una solicitud para <strong className="text-neutral-200 break-all">{email}</strong>, te enviamos un
          enlace para ver su estado. Revisa también la carpeta de spam.
        </p>
        <Link to="/" className="text-[#8B5CF6] hover:underline text-sm" data-testid="company-status-home-link">
          ← Volver al inicio
        </Link>
      </div>
    );
  }

  return (
    <div className="tactile-card p-8 max-w-md w-full" data-testid="company-status-link-form">
      <div className="text-center mb-6">
        <Building2 className="w-10 h-10 text-[#8B5CF6] mx-auto mb-3" />
        <h1 className="font-display text-2xl mb-2">Seguimiento de solicitud</h1>
        <p className="text-neutral-400 text-sm">
          Escribe el correo con el que enviaste tu solicitud de cuenta Empresa y te enviaremos un enlace seguro para ver su estado.
        </p>
      </div>
      <div className="space-y-4">
        <div>
          <Label htmlFor="track-email" className="micro-label text-neutral-500">Correo de la empresa</Label>
          <Input id="track-email" data-testid="company-status-email-input" type="email" value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder="empresa@correo.com"
            onKeyDown={(e) => e.key === "Enter" && submit()}
            className="rounded-none bg-black/40 text-white h-11 mt-1 border-white/10" />
        </div>
        {captchaCfg?.enabled && (
          <div className="flex justify-center" data-testid="company-status-captcha">
            <Turnstile key={captchaKey} siteKey={captchaCfg.site_key}
              options={{ theme: getTheme() === "light" ? "light" : "dark", language: "es" }}
              onSuccess={(tk) => setCaptchaToken(tk)} onExpire={() => setCaptchaToken("")} onError={() => setCaptchaToken("")} />
          </div>
        )}
        <Button onClick={submit} disabled={!canSend} data-testid="company-status-send-btn"
          className="w-full rounded-none bg-[#8B5CF6] hover:bg-[#7C4DF0] text-white font-semibold disabled:opacity-40">
          {sending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
          {sending ? "Enviando…" : "Enviarme el enlace"}
        </Button>
        <div className="text-center">
          <Link to="/" className="text-xs text-neutral-500 hover:text-neutral-300" data-testid="company-status-home-link">
            ← Volver al inicio
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function CompanyRequestStatus() {
  const { token } = useParams();
  const [state, setState] = useState(token ? "loading" : "form");
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const didRun = useRef(false);

  useEffect(() => {
    if (!token || didRun.current) return;
    didRun.current = true;
    axios.get(`${API}/company-signup/status/${token}`)
      .then((r) => { setData(r.data); setState("ok"); })
      .catch((e) => { setErr(e.response?.data?.detail || "Enlace no válido o caducado."); setState("err"); });
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] text-white p-4" data-testid="company-request-status-page">
      {state === "form" && <RequestLinkForm />}
      {state === "loading" && (
        <div className="tactile-card p-10 max-w-md w-full text-center">
          <Loader2 className="w-10 h-10 text-[#8B5CF6] animate-spin mx-auto mb-4" />
          <p className="text-neutral-400">Consultando el estado de tu solicitud…</p>
        </div>
      )}
      {state === "ok" && data && <StatusCard data={data} />}
      {state === "err" && (
        <div className="tactile-card p-10 max-w-md w-full text-center" data-testid="company-status-error">
          <XCircle className="w-12 h-12 text-[#EF4444] mx-auto mb-4" />
          <h1 className="font-display text-2xl mb-2">Enlace no válido</h1>
          <p className="text-neutral-400 text-sm mb-6">{err}</p>
          <Link to="/empresa/seguimiento" className="inline-flex items-center gap-1.5 text-[#8B5CF6] hover:underline text-sm" data-testid="company-status-retry-link">
            <Search className="w-4 h-4" /> Solicitar un enlace nuevo
          </Link>
        </div>
      )}
    </div>
  );
}
