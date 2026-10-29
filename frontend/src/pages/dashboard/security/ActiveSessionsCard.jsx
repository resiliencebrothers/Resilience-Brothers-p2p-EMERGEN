import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { toast } from "sonner";
import { Monitor, Smartphone, RefreshCw, X, ShieldCheck } from "lucide-react";

const isMobile = (os) => ["iPhone", "iPad", "Android"].includes(os);

export const ActiveSessionsCard = () => {
  const { t, i18n } = useTranslation();
  const [sessions, setSessions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revokingId, setRevokingId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/auth/sessions`, { withCredentials: true });
      setSessions(r.data?.sessions || []);
    } catch (e) {
      toast.error(t("security.sessions.loadError"));
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const revoke = async (s) => {
    if (revokingId) return;
    setRevokingId(s.id);
    try {
      const r = await axios.post(
        `${API}/auth/sessions/revoke`,
        { session_id: s.id },
        { withCredentials: true },
      );
      if (r.data?.current_session_ended) {
        window.location.href = "/";
        return;
      }
      toast.success(t("security.sessions.revoked"));
      await load();
    } catch (e) {
      toast.error(t("security.sessions.revokeError"));
    } finally {
      setRevokingId("");
    }
  };

  const fmtDate = (iso) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString(i18n.language === "en" ? "en-US" : "es-ES", {
        dateStyle: "medium", timeStyle: "short",
      });
    } catch { return iso; }
  };

  return (
    <div className="tactile-card p-5 border border-white/10" data-testid="active-sessions-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Monitor className="w-5 h-5 text-sky-400 mt-0.5 shrink-0" />
          <div>
            <h2 className="font-display text-lg">{t("security.sessions.title")}</h2>
            <p className="text-neutral-500 text-sm mt-1">{t("security.sessions.desc")}</p>
          </div>
        </div>
        <button
          type="button"
          data-testid="active-sessions-refresh"
          onClick={load}
          disabled={loading}
          className="p-2 text-neutral-400 hover:text-white transition-colors disabled:opacity-40"
          aria-label={t("security.sessions.refresh")}
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="mt-4 space-y-2" data-testid="active-sessions-list">
        {loading && sessions === null && (
          <p className="text-neutral-500 text-sm" data-testid="active-sessions-loading">
            {t("security.sessions.loading")}
          </p>
        )}
        {sessions && sessions.length === 0 && !loading && (
          <p className="text-neutral-500 text-sm" data-testid="active-sessions-empty">
            {t("security.sessions.empty")}
          </p>
        )}
        {(sessions || []).map((s) => {
          const Icon = isMobile(s.os) ? Smartphone : Monitor;
          return (
            <div
              key={s.id}
              data-testid={`session-row-${s.id}`}
              className="flex items-center justify-between gap-3 border border-white/10 bg-black/20 px-3 py-2.5"
            >
              <div className="flex items-center gap-3 min-w-0">
                <Icon className="w-4 h-4 text-neutral-300 shrink-0" />
                <div className="min-w-0">
                  <div className="text-sm text-white truncate">
                    {s.browser} · {s.os}
                    {s.current && (
                      <span
                        data-testid="session-current-badge"
                        className="ml-2 inline-flex items-center gap-1 text-[0.65rem] uppercase tracking-wider text-emerald-300 border border-emerald-500/40 px-1.5 py-0.5"
                      >
                        <ShieldCheck className="w-3 h-3" /> {t("security.sessions.thisDevice")}
                      </span>
                    )}
                  </div>
                  <div className="text-[0.7rem] text-neutral-500 truncate">
                    {s.ip ? `${s.ip} · ` : ""}{fmtDate(s.created_at)}
                  </div>
                </div>
              </div>
              {!s.current && (
                <button
                  type="button"
                  data-testid={`revoke-session-btn-${s.id}`}
                  onClick={() => revoke(s)}
                  disabled={revokingId === s.id}
                  className="shrink-0 inline-flex items-center gap-1 px-3 py-1.5 text-xs font-bold uppercase tracking-wider border border-red-500/50 text-red-300 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                >
                  <X className="w-3.5 h-3.5" />
                  {revokingId === s.id ? t("security.sessions.closing") : t("security.sessions.close")}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ActiveSessionsCard;
