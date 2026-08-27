"""Email notifications via Resend.

iter68 — customer-facing emails and templates are localized based on the
recipient's `preferred_language` (see routes/profile.py PATCH /profile/language).
The `_L(es, en, lang)` helper collapses inline text swaps into a single line.
Admin-recipient emails (monthly audit, monthly revenue) stay in Spanish since
the ops team is Spanish-speaking.
"""
import os
import base64
import logging
import time
import uuid as _uuid
from datetime import datetime, timezone
import resend

logger = logging.getLogger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")
EMAIL_SEND_ENABLED = os.environ.get("EMAIL_SEND_ENABLED", "true").strip().lower() != "false"
SENDER = os.environ.get("EMAIL_SENDER", "Resilience Brothers <onboarding@resend.dev>")
REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "")
APP_URL = os.environ.get("APP_PUBLIC_URL", "")

# iter147 — delivery ledger: every send attempt is persisted to
# `email_events` so staff can SEE why a user's email never arrived.
_mongo_client = None


def _record_event(to: str, subject: str, kind: str, status: str,
                  error: str = "", provider_id: str = "", attempts: int = 1,
                  html_body: str = "") -> str:
    """Persist a delivery event and return its id (for `retried_from` refs).

    `html_body` is stored so the "Reenviar este email" support flow can
    replay exactly the same rendered HTML (iter196). Suppressed events
    (dev/CI) skip the html to save space — they're never worth retrying.
    """
    global _mongo_client
    event_id = f"emev_{_uuid.uuid4().hex[:12]}"
    try:
        if _mongo_client is None:
            from pymongo import MongoClient
            _mongo_client = MongoClient(os.environ["MONGO_URL"])
        doc = {
            "id": event_id,
            "to": (to or "").lower().strip(),
            "subject": subject,
            "kind": kind or "",
            "status": status,  # sent | failed | suppressed
            "error": (error or "")[:500],
            "provider_id": provider_id or "",
            "attempts": attempts,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if status != "suppressed" and html_body:
            doc["html_body"] = html_body
        _mongo_client[os.environ["DB_NAME"]].email_events.insert_one(doc)
    except Exception as e:
        logger.error(f"email_events record failed: {e}")
    return event_id


def _L(es: str, en: str, lang: str = "es") -> str:
    """Pick the localized string. `en-GB`, `en-US`, `EN` all resolve to English;
    anything else (including empty) falls back to Spanish."""
    return en if (lang or "").lower().startswith("en") else es


def _base_template(title: str, body_html: str, lang: str = "es") -> str:
    logo_url = f"{APP_URL}/branding/logo-300.png" if APP_URL else ""
    logo_html = f'<img src="{logo_url}" alt="Resilience Brothers" width="48" height="48" style="display:block;border:0;outline:none;">' if logo_url else '<span style="display:inline-block;background:#8B5CF6;color:#000;font-weight:900;padding:6px 10px;letter-spacing:0.5px;">RB</span>'
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:'Helvetica Neue',Arial,sans-serif;color:#FFFFFF;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0A0A0A;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#141414;border:1px solid rgba(255,255,255,0.08);">
        <tr><td style="padding:24px 32px;border-bottom:1px solid rgba(255,255,255,0.08);">
          <table width="100%"><tr>
            <td style="vertical-align:middle;">{logo_html}</td>
            <td style="vertical-align:middle;padding-left:12px;"><span style="font-weight:800;color:#fff;font-size:14px;letter-spacing:1px;">RESILIENCE BROTHERS</span></td>
            <td align="right"><span style="font-size:10px;color:#A3A3A3;letter-spacing:2px;text-transform:uppercase;">{_L("P2P · Notificación", "P2P · Notification", lang)}</span></td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:32px;">
          <h1 style="font-size:28px;line-height:1.1;margin:0 0 16px;color:#fff;font-weight:900;letter-spacing:-0.5px;">{title}</h1>
          {body_html}
        </td></tr>
        <tr><td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.08);background:#0c0c0c;">
          <p style="margin:0;color:#A3A3A3;font-size:12px;line-height:1.5;">{_L(
              "Este mensaje fue enviado por Resilience Brothers · Plataforma P2P de comercio global. Si tienes preguntas, responde directamente a este correo.",
              "This message was sent by Resilience Brothers · Global P2P trading platform. If you have questions, reply directly to this email.",
              lang,
          )}</p>
        </td></tr>
      </table>
      <p style="color:#525252;font-size:11px;margin-top:16px;letter-spacing:1px;text-transform:uppercase;">© Resilience Brothers · Global Trade Infrastructure</p>
    </td></tr>
  </table>
</body></html>"""


def _clear_bounce_alert(to: str) -> None:
    """iter196 — a healthy send closes any open bounce alert so the
    admin dashboard doesn't stay flagged after the mailbox recovers."""
    try:
        from services.email_bounce_alerts import clear_alert_on_success
        clear_alert_on_success(to, _mongo_client)
    except Exception as e:
        logger.error(f"[bounce] clear_alert_on_success: {e}")


def _register_bounce_failure(to: str) -> None:
    """iter196 — 3 consecutive failed rows for the same recipient trigger a
    staff alert. Detection is sync + best-effort; dispatch is handled by
    the APScheduler `email_bounce_dispatch` job."""
    try:
        from services.email_bounce_alerts import record_failure_and_maybe_alert
        record_failure_and_maybe_alert(to, _mongo_client)
    except Exception as e:
        logger.error(f"[bounce] record_failure_and_maybe_alert: {e}")


def _send_with_retries(params: dict, to: str, subject: str, kind: str,
                       html: str) -> bool:
    """iter147 — up to 3 attempts with short backoff (Resend rate limits /
    transient 5xx), and every outcome is persisted to `email_events`."""
    last_err = None
    for attempt in range(1, 4):
        try:
            resp = resend.Emails.send(params)
            logger.info(f"Email sent to {to}: id={resp.get('id')}")
            _record_event(to, subject, kind, "sent",
                          provider_id=str(resp.get("id") or ""), attempts=attempt,
                          html_body=html)
            _clear_bounce_alert(to)
            return True
        except Exception as e:
            last_err = e
            logger.error(f"Resend email failed for {to} (attempt {attempt}/3): {e}")
            if attempt < 3:
                time.sleep(0.6 * attempt)
    _record_event(to, subject, kind, "failed", error=str(last_err), attempts=3,
                  html_body=html)
    _register_bounce_failure(to)
    return False


def _send(to: str, subject: str, html: str, attachments: list = None,
          kind: str = "") -> bool:
    if not EMAIL_SEND_ENABLED:
        logger.info(f"[email-suppressed] to={to} subject={subject!r} (EMAIL_SEND_ENABLED=false)")
        _record_event(to, subject, kind, "suppressed")
        return True
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set, skipping email")
        _record_event(to, subject, kind, "failed", error="RESEND_API_KEY not set",
                      html_body=html)
        return False
    if not to:
        return False
    params = {"from": SENDER, "to": [to], "subject": subject, "html": html}
    if REPLY_TO:
        params["reply_to"] = REPLY_TO
    if attachments:
        params["attachments"] = attachments
    return _send_with_retries(params, to, subject, kind, html)


def resend_email_event(event: dict) -> tuple[bool, str]:
    """iter196 — support tool: replay the exact rendered HTML of an
    existing `email_events` row. Returns (ok, message)."""
    if event.get("status") == "suppressed":
        return False, "El envío estaba desactivado cuando se registró — no hay cuerpo HTML guardado para reintentar."
    html = event.get("html_body")
    if not html:
        return False, "Este correo se registró antes de habilitar el reintento manual (sin cuerpo HTML guardado)."
    to = event.get("to")
    if not to:
        return False, "Destinatario vacío."
    ok = _send(to, event.get("subject", ""), html, kind=event.get("kind", ""))
    return ok, "Reintento enviado" if ok else "Resend rechazó el reintento (ver historial)"



def notify_monthly_audit(to: str, period_label: str, kpis: dict,
                          integrity_hash: str, pdf_bytes: bytes) -> bool:
    """Email the monthly audit PDF to a compliance / owner mailbox."""
    subject = f"Reporte mensual de auditoría · {period_label}"
    total = int(kpis.get("total_actions", 0))
    distinct = int(kpis.get("distinct_actors", 0))
    anti = sum(item.get("count", 0) for item in (kpis.get("anti_fraud") or []))
    top_actors_html = ""
    for a in (kpis.get("top_actors") or [])[:3]:
        name = a.get("name") or a.get("email") or "—"
        top_actors_html += (
            f"<tr><td style='padding:4px 0;color:#A3A3A3;font-size:13px;'>{name}</td>"
            f"<td style='padding:4px 0;color:#fff;font-family:monospace;text-align:right;'>{a.get('count', 0)}</td></tr>"
        )
    if not top_actors_html:
        top_actors_html = (
            "<tr><td style='padding:4px 0;color:#A3A3A3;font-size:13px;'>—</td>"
            "<td style='padding:4px 0;color:#fff;font-family:monospace;text-align:right;'>0</td></tr>"
        )
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">
        Reporte automático de trazabilidad del cierre de <strong style="color:#fff;">{period_label}</strong>.
        Adjunto encontrarás el PDF con resumen ejecutivo, tabla detallada de todas las
        acciones staff/admin y la firma SHA-256 para integridad forense.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Acciones totales</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{total}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Actores distintos</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{distinct}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Señales anti-fraude</td>
            <td style="padding:6px 0;color:{'#EF4444' if anti > 0 else '#22C55E'};font-family:monospace;text-align:right;font-weight:bold;">{anti}</td></tr>
      </table>
      <p style="margin:18px 0 6px;color:#8B5CF6;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Top actores</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:12px 20px;">
        {top_actors_html}
      </table>
      <p style="margin:22px 0 6px;color:#8B5CF6;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Firma de integridad</p>
      <p style="margin:0 0 4px;color:#A3A3A3;font-size:12px;">Guarda este hash junto con el PDF — es tu prueba de que las filas no fueron alteradas después de la exportación.</p>
      <p style="margin:6px 0 0;color:#fff;font-family:monospace;font-size:11px;word-break:break-all;background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:10px 14px;">{integrity_hash}</p>
      <p style="margin:22px 0 8px;color:#A3A3A3;font-size:13px;">
        También puedes regenerar el reporte en cualquier momento desde <em>/admin/audit</em>.
      </p>
    """
    attachment = {
        "filename": f"auditoria-{period_label.replace(' ', '-')}.pdf",
        "content": base64.b64encode(pdf_bytes).decode("ascii"),
    }
    return _send(to, subject, _base_template("Reporte mensual de auditoría", body),
                 attachments=[attachment])


def notify_monthly_revenue(to: str, period_label: str, totals: dict, pdf_bytes: bytes) -> bool:
    """Email the monthly revenue PDF to an admin."""
    subject = f"Reporte mensual de ganancias · {period_label}"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">
        Reporte automático del cierre mensual de <strong style="color:#fff;">{period_label}</strong>.
        Adjunto encontrarás el PDF con desglose diario, totales y gráfico de tendencia.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Ganancia P2P</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{totals['p2p']:.2f} USDT</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Ganancia Marketplace</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{totals['marketplace']:.2f} USDT</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Comisiones USDT (conversiones)</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{totals.get('conversion_fees', 0.0):.2f} USDT</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Ganancia TOTAL</td>
            <td style="padding:6px 0;color:#22C55E;font-family:monospace;text-align:right;font-weight:bold;font-size:15px;">{totals['total']:.2f} USDT</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Volumen P2P</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{totals['volume']:.2f} USDT</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Órdenes</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{totals['orders']}</td></tr>
      </table>
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">
        También puedes descargarlo desde la sección <em>Ingresos</em> del panel admin.
      </p>
    """
    attachment = {
        "filename": f"ganancia-{period_label}.pdf",
        "content": base64.b64encode(pdf_bytes).decode("ascii"),
    }
    return _send(to, subject, _base_template("Cierre mensual", body), attachments=[attachment])


def notify_security_selfaudit(to: str, report: dict) -> bool:
    """iter116 — email the monthly security self-audit checklist to an admin."""
    verdict = (report.get("verdict") or "pass").lower()
    summary = report.get("summary") or {}
    verdict_color = {"pass": "#22C55E", "warn": "#F59E0B", "fail": "#EF4444"}.get(verdict, "#A3A3A3")
    verdict_label = {"pass": "TODO EN ORDEN", "warn": "REVISAR AVISOS",
                     "fail": "ACCIÓN REQUERIDA"}.get(verdict, verdict.upper())
    subject = f"Auditoría de seguridad automática · {verdict_label}"
    status_dot = {"pass": "#22C55E", "warn": "#F59E0B", "fail": "#EF4444"}
    rows = ""
    for c in report.get("checks", []):
        color = status_dot.get(c.get("status"), "#A3A3A3")
        rows += (
            "<tr>"
            f"<td style='padding:8px 0;vertical-align:top;width:14px;'>"
            f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};'></span></td>"
            f"<td style='padding:8px 8px;vertical-align:top;'>"
            f"<div style='color:#fff;font-size:13px;'>{c.get('id')} · {c.get('title')}</div>"
            f"<div style='color:#A3A3A3;font-size:12px;line-height:1.5;margin-top:2px;'>{c.get('detail')}</div>"
            "</td></tr>"
        )
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        Chequeo automático mensual de las invariantes de seguridad de la plataforma.
        Cada punto se re-verifica contra el código y la configuración en vivo.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid {verdict_color}40;padding:16px 20px;margin-bottom:16px;">
        <tr>
          <td style="color:#A3A3A3;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Veredicto</td>
          <td style="text-align:right;color:{verdict_color};font-family:monospace;font-weight:bold;font-size:15px;">{verdict_label}</td>
        </tr>
        <tr>
          <td style="color:#A3A3A3;font-size:12px;padding-top:8px;">Resultados</td>
          <td style="text-align:right;padding-top:8px;color:#fff;font-family:monospace;font-size:12px;">
            <span style="color:#22C55E;">{summary.get('pass', 0)} OK</span> ·
            <span style="color:#F59E0B;">{summary.get('warn', 0)} avisos</span> ·
            <span style="color:#EF4444;">{summary.get('fail', 0)} fallos</span>
          </td>
        </tr>
      </table>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:8px 16px;">
        {rows}
      </table>
      <p style="margin:20px 0 6px;color:#A3A3A3;font-size:12px;">
        Puedes re-ejecutar este chequeo en cualquier momento desde
        <em>POST /api/admin/security/self-audit/run-now</em>.
      </p>
    """
    return _send(to, subject, _base_template("Auditoría de seguridad", body))



# ============== iter17 — email verification & password reset ==============

def _app_url() -> str:
    return APP_URL.rstrip("/") if APP_URL else "https://p2p.resiliencebrothers.com"
def _ops_row(cols) -> str:
    tds = "".join(
        f'<td style="padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.06);color:#D4D4D4;font-size:12px;">{c}</td>'
        for c in cols)
    return f"<tr>{tds}</tr>"


def _ops_age(v) -> str:
    return f"{v}h" if v is not None else "—"


def _ops_section(title: str, headers: list, rows: list) -> str:
    if not rows:
        return ""
    ths = "".join(
        f'<th align="left" style="padding:6px 8px;color:#A3A3A3;font-size:10px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid rgba(255,255,255,0.15);">{h}</th>'
        for h in headers)
    return (f'<h2 style="font-size:15px;color:#FBBF24;margin:24px 0 8px;">{title} · {len(rows)}</h2>'
            f'<table width="100%" cellpadding="0" cellspacing="0"><tr>{ths}</tr>{"".join(rows)}</table>')


def _ops_under_review_rows(report: dict) -> list:
    return [_ops_row([u.get("name") or u.get("email") or u.get("user_id") or "—",
                      u.get("phone") or "—", _ops_age(u.get("age_hours"))])
            for u in report.get("under_review", [])]


def _ops_appeal_rows(report: dict) -> list:
    return [_ops_row([a.get("user_name") or a.get("user_email") or a.get("user_id") or "—",
                      (a.get("message") or "")[:60] or "—", _ops_age(a.get("age_hours"))])
            for a in report.get("appeals", [])]


def _ops_ticket_rows(report: dict) -> list:
    return [_ops_row([t.get("user_name") or t.get("user_email") or "—",
                      (t.get("subject") or "")[:50] or "—",
                      t.get("category") or "—", _ops_age(t.get("age_hours"))])
            for t in report.get("tickets", [])]


def notify_daily_ops_report(to: str, report: dict, lang: str = "es") -> bool:
    """iter176 — daily 08:00 (Cuba) ops digest: cases unresolved > 48h."""
    hours = report.get("hours", 48)
    total = report.get("total", 0)

    body_html = (
        f'<p style="color:#D4D4D4;font-size:14px;line-height:1.6;">'
        f'{_L(f"Estos <strong>{total}</strong> casos llevan más de <strong>{hours} horas</strong> sin resolverse y requieren atención del equipo:", f"These <strong>{total}</strong> cases have been unresolved for more than <strong>{hours} hours</strong> and need the team&#39;s attention:", lang)}</p>'
        + _ops_section(_L("Cuentas en revisión anti-fraude", "Accounts under anti-fraud review", lang),
                       [_L("Usuario", "User", lang), _L("Teléfono", "Phone", lang), _L("Antigüedad", "Age", lang)],
                       _ops_under_review_rows(report))
        + _ops_section(_L("Apelaciones pendientes", "Pending appeals", lang),
                       [_L("Usuario", "User", lang), _L("Mensaje", "Message", lang), _L("Antigüedad", "Age", lang)],
                       _ops_appeal_rows(report))
        + _ops_section(_L("Tickets de soporte sin responder", "Unanswered support tickets", lang),
                       [_L("Usuario", "User", lang), _L("Asunto", "Subject", lang),
                        _L("Categoría", "Category", lang), _L("Antigüedad", "Age", lang)],
                       _ops_ticket_rows(report))
        + f'<p style="margin-top:28px;"><a href="{_app_url()}/admin" style="background:#8B5CF6;color:#fff;padding:10px 18px;text-decoration:none;font-weight:700;font-size:13px;">{_L("Abrir panel admin", "Open admin panel", lang)}</a></p>'
    )
    subject = _L(f"⚠️ {total} casos pendientes +{hours}h — Reporte diario de operaciones",
                 f"⚠️ {total} cases pending +{hours}h — Daily ops report", lang)
    return _send(to, subject,
                 _base_template(_L("Reporte diario de operaciones", "Daily ops report", lang),
                                body_html, lang),
                 kind="daily_ops_report")


def notify_email_change_code(to: str, name: str, code: str, lang: str = "es") -> bool:
    """iter55.20 — send OTP to the NEW email during profile email change."""
    subject = _L("Confirma tu nuevo email · Resilience Brothers",
                 "Confirm your new email · Resilience Brothers", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">
        {_L(f"Hola {name or 'usuario'} — recibimos una solicitud para actualizar tu email a esta dirección. Ingresa el siguiente código en la plataforma para confirmar.",
            f"Hi {name or 'user'} — we received a request to update your email to this address. Enter the following code on the platform to confirm.", lang)}
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(234,179,8,0.4);padding:24px;text-align:center;">
        <div style="color:#8B5CF6;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">{_L("Código de confirmación", "Confirmation code", lang)}</div>
        <div style="color:#fff;font-family:monospace;font-size:32px;letter-spacing:8px;font-weight:bold;">{code}</div>
      </div>
      <p style="color:#A3A3A3;font-size:13px;line-height:1.6;margin:22px 0 0;">
        {_L("El código expira en 15 minutos. Si no solicitaste este cambio, ignora este mensaje — tu email actual seguirá activo.",
            "The code expires in 15 minutes. If you didn't request this change, ignore this message — your current email will stay active.", lang)}
      </p>
    """
    return _send(to, subject, _base_template(_L("Confirma tu nuevo email", "Confirm your new email", lang), body, lang))


def notify_email_change_alert(to: str, name: str, new_email_masked: str, lang: str = "es") -> bool:
    """iter55.20 — heads-up to the OLD email so silent takeovers get noticed."""
    subject = _L("Alerta de seguridad · Cambio de email en curso",
                 "Security alert · Email change in progress", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        {_L(f"Hola {name or 'usuario'} — se solicitó cambiar el email de tu cuenta a",
            f"Hi {name or 'user'} — a request was made to change your account email to", lang)}
        <strong style="color:#fff;font-family:monospace;">{new_email_masked}</strong>.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(239,68,68,0.4);padding:18px;">
        <p style="margin:0 0 10px;color:#EF4444;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">{_L("¿No fuiste tú?", "Wasn't you?", lang)}</p>
        <p style="margin:0;color:#A3A3A3;font-size:13px;line-height:1.6;">
          {_L("Si <strong style='color:#fff;'>no</strong> reconoces esta solicitud, cambia tu contraseña de inmediato y contacta al equipo. El cambio no se aplicará hasta que se confirme el código enviado al nuevo email.",
              "If you do <strong style='color:#fff;'>not</strong> recognize this request, change your password immediately and contact the team. The change will not apply until the code sent to the new email is confirmed.", lang)}
        </p>
      </div>
      <p style="color:#A3A3A3;font-size:12px;margin:22px 0 0;">
        {_L("Si sí fuiste tú, ignora este correo — recibirás una notificación cuando el cambio se complete.",
            "If it was you, ignore this email — you'll get a notification when the change completes.", lang)}
      </p>
    """
    return _send(to, subject, _base_template(_L("Alerta de seguridad", "Security alert", lang), body, lang))


def notify_email_change_success(to: str, name: str, other_email_masked: str, lang: str = "es") -> bool:
    """iter55.20 — post-change confirmation, sent to both old and new inbox."""
    subject = _L("Email actualizado · Resilience Brothers",
                 "Email updated · Resilience Brothers", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        {_L(f"Hola {name or 'usuario'} — el email de tu cuenta fue actualizado correctamente. La otra dirección asociada es",
            f"Hi {name or 'user'} — your account email was updated successfully. The other address on file is", lang)}
        <strong style="color:#fff;font-family:monospace;">{other_email_masked}</strong>.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(34,197,94,0.4);padding:18px;">
        <p style="margin:0;color:#22C55E;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">{_L("Cambio aplicado", "Change applied", lang)}</p>
      </div>
      <p style="color:#A3A3A3;font-size:13px;margin:22px 0 0;line-height:1.6;">
        {_L("A partir de ahora recibirás todos los avisos en tu email actualizado. Si no reconoces este cambio, contacta al equipo de soporte de inmediato.",
            "From now on you'll receive all notices at your updated email. If you don't recognize this change, contact support immediately.", lang)}
      </p>
    """
    return _send(to, subject, _base_template(_L("Email actualizado", "Email updated", lang), body, lang))


def notify_phone_change_approved(to: str, name: str, new_phone_masked: str, lang: str = "es") -> bool:
    """iter55.20b — inform the client their phone-change request was approved."""
    subject = _L("Tu nuevo teléfono fue verificado · Resilience Brothers",
                 "Your new phone was verified · Resilience Brothers", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        {_L(f"Hola {name or 'usuario'} — el equipo aprobó tu solicitud de cambio de teléfono. A partir de ahora recibirás los avisos SMS en",
            f"Hi {name or 'user'} — the team approved your phone-change request. From now on you'll receive SMS notices at", lang)}
        <strong style="color:#fff;font-family:monospace;">{new_phone_masked}</strong>.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(34,197,94,0.4);padding:18px;">
        <p style="margin:0;color:#22C55E;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">{_L("Cambio aplicado", "Change applied", lang)}</p>
      </div>
      <p style="color:#A3A3A3;font-size:13px;line-height:1.6;margin:22px 0 0;">
        {_L("Si <strong style='color:#fff;'>no</strong> reconoces este cambio, contacta al equipo de soporte de inmediato — el número recién verificado podría permitir recuperar la cuenta.",
            "If you do <strong style='color:#fff;'>not</strong> recognize this change, contact support immediately — the newly verified number could allow account recovery.", lang)}
      </p>
    """
    return _send(to, subject, _base_template(_L("Teléfono verificado", "Phone verified", lang), body, lang))


def notify_phone_change_rejected(to: str, name: str, new_phone_masked: str,
                                  reason: str, lang: str = "es") -> bool:
    """iter55.20b — inform the client their phone-change request was rejected."""
    subject = _L("Solicitud de cambio de teléfono rechazada · Resilience Brothers",
                 "Phone-change request rejected · Resilience Brothers", lang)
    safe_reason = (reason or "").strip()[:400] or _L("Sin motivo especificado", "No reason provided", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        {_L(f"Hola {name or 'usuario'} — el equipo revisó tu solicitud de cambio de teléfono a",
            f"Hi {name or 'user'} — the team reviewed your phone-change request to", lang)}
        <strong style="color:#fff;font-family:monospace;">{new_phone_masked}</strong>
        {_L("y decidió no aplicarlo por ahora. Tu número actual sigue activo.",
            "and decided not to apply it for now. Your current number is still active.", lang)}
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(239,68,68,0.4);padding:18px;">
        <p style="margin:0 0 8px;color:#EF4444;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">{_L("Motivo", "Reason", lang)}</p>
        <p style="margin:0;color:#fff;font-size:13px;line-height:1.6;">{safe_reason}</p>
      </div>
      <p style="color:#A3A3A3;font-size:13px;line-height:1.6;margin:22px 0 0;">
        {_L("Puedes volver a solicitar el cambio desde tu perfil aportando la documentación de respaldo que el equipo indique, o contactar a soporte para cualquier duda.",
            "You can request the change again from your profile with the supporting documentation the team requests, or contact support for any questions.", lang)}
      </p>
    """
    return _send(to, subject, _base_template(_L("Cambio de teléfono rechazado", "Phone change rejected", lang), body, lang))


def notify_email_verification(to: str, name: str, token: str, lang: str = "es") -> bool:
    link = f"{_app_url()}/auth/verify-email/{token}"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.7;margin:0 0 24px;">
        {_L(f"¡Hola {name or 'usuario'}! 👋<br><br>Gracias por crear tu cuenta en Resilience Brothers. Para empezar a operar necesitamos confirmar que este correo te pertenece.",
            f"Hi {name or 'user'}! 👋<br><br>Thanks for creating your account at Resilience Brothers. To start trading we need to confirm that this email belongs to you.", lang)}
      </p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:8px 0 24px;">
          <a href="{link}" style="background:#8B5CF6;color:#000;text-decoration:none;
             padding:14px 36px;font-weight:bold;font-family:Arial;letter-spacing:1px;
             display:inline-block;">{_L("VERIFICAR MI EMAIL", "VERIFY MY EMAIL", lang)}</a>
        </td></tr>
      </table>
      <p style="color:#666;font-size:12px;margin:0 0 6px;">{_L("El enlace expira en 24 horas.", "The link expires in 24 hours.", lang)}</p>
      <p style="color:#666;font-size:11px;word-break:break-all;">{_L("O copia:", "Or copy:", lang)} {link}</p>
    """
    return _send(to, _L("Verifica tu correo · Resilience Brothers", "Verify your email · Resilience Brothers", lang),
                 _base_template(_L("Verifica tu cuenta", "Verify your account", lang), body, lang),
                 kind="email_verification")


def notify_password_reset(to: str, name: str, token: str, lang: str = "es") -> bool:
    link = f"{_app_url()}/auth/reset-password/{token}"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.7;margin:0 0 24px;">
        {_L(f"Hola {name or 'usuario'},<br><br>Recibimos una solicitud para restablecer la contraseña de tu cuenta en Resilience Brothers. Si fuiste tú, haz clic abajo. Si no, ignora este correo.",
            f"Hi {name or 'user'},<br><br>We received a request to reset your Resilience Brothers account password. If it was you, click below. If not, ignore this email.", lang)}
      </p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:8px 0 24px;">
          <a href="{link}" style="background:#8B5CF6;color:#000;text-decoration:none;
             padding:14px 36px;font-weight:bold;font-family:Arial;letter-spacing:1px;
             display:inline-block;">{_L("CREAR NUEVA CONTRASEÑA", "CREATE NEW PASSWORD", lang)}</a>
        </td></tr>
      </table>
      <p style="color:#666;font-size:12px;margin:0 0 6px;">{_L("El enlace expira en 2 horas.", "The link expires in 2 hours.", lang)}</p>
      <p style="color:#666;font-size:11px;word-break:break-all;">{_L("O copia:", "Or copy:", lang)} {link}</p>
    """
    return _send(to, _L("Restablecer contraseña · Resilience Brothers", "Reset your password · Resilience Brothers", lang),
                 _base_template(_L("Recuperar contraseña", "Recover password", lang), body, lang),
                 kind="password_reset")


def notify_password_changed(to: str, name: str, lang: str = "es") -> bool:
    """iter55.30 — post-hoc security confirmation sent to the account owner
    right after `/api/profile/password/change` succeeds."""
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.7;margin:0 0 20px;">
        {_L(f"Hola {name or 'usuario'},<br><br>La contraseña de tu cuenta en <strong style='color:#fff;'>Resilience Brothers</strong> fue actualizada correctamente. Todas tus otras sesiones fueron cerradas por seguridad.",
            f"Hi {name or 'user'},<br><br>Your <strong style='color:#fff;'>Resilience Brothers</strong> account password was updated successfully. All your other sessions were closed for security.", lang)}
      </p>
      <div style="border-left:3px solid #EF4444;background:#1a0a0a;padding:14px 18px;margin:12px 0 22px;">
        <p style="color:#EF4444;font-size:13px;font-weight:bold;margin:0 0 6px;">
          {_L("¿No fuiste tú?", "Wasn't you?", lang)}
        </p>
        <p style="color:#A3A3A3;font-size:12px;margin:0;line-height:1.5;">
          {_L('Cambia tu contraseña de inmediato desde la opción "¿Olvidaste tu contraseña?" y contacta a soporte. Nunca compartimos códigos ni contraseñas por email.',
              'Change your password immediately via the "Forgot password?" option and contact support. We never share codes or passwords via email.', lang)}
        </p>
      </div>
      <p style="color:#666;font-size:11px;margin:0;">
        {_L("Fecha de cambio:", "Change date:", lang)} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
      </p>
    """
    return _send(to, _L("Tu contraseña fue actualizada · Resilience Brothers", "Your password was updated · Resilience Brothers", lang),
                 _base_template(_L("Contraseña cambiada", "Password changed", lang), body, lang))


from dataclasses import dataclass


@dataclass
class VipLedgerEmailContext:
    """iter111 — payload for `notify_vip_ledger_statement`.

    Collapsing 9 positional args into one dataclass keeps call sites
    self-documenting and avoids the argument-count anti-pattern flagged
    by the code-review agent.
    """
    to: str
    vip_name: str
    since: str
    until: str
    movements_count: int
    pdf_bytes: bytes
    issuer_name: str
    personal_note: str = ""
    lang: str = "es"


def _ledger_period_label(since: str, until: str) -> str:
    if since and until:
        return f"{since} → {until}"
    if since:
        return f"desde {since}"
    if until:
        return f"hasta {until}"
    return "histórico completo"


def _ledger_note_block(ctx: VipLedgerEmailContext) -> str:
    safe_note = (ctx.personal_note or "").strip()[:600]
    if not safe_note:
        return ""
    label = _L("Nota de", "Note from", ctx.lang)
    return (
        f'<div style="background:#0a0a0a;border-left:3px solid #8B5CF6;'
        f'padding:12px 16px;margin:20px 0;">'
        f'<p style="margin:0 0 4px;color:#8B5CF6;font-size:11px;'
        f'text-transform:uppercase;letter-spacing:1px;">'
        f'{label} {ctx.issuer_name}</p>'
        f'<p style="margin:0;color:#fff;font-size:13px;line-height:1.5;">'
        f'{safe_note}</p></div>'
    )


def _ledger_body_html(ctx: VipLedgerEmailContext, period: str) -> str:
    lang = ctx.lang
    intro = _L(
        f"Hola — adjunto encontrarás el estado de cuenta oficial del ledger VIP "
        f"de <strong style='color:#fff;'>{ctx.vip_name or 'usuario'}</strong> "
        f"correspondiente al período {period}.",
        f"Hi — attached is the official VIP ledger statement for "
        f"<strong style='color:#fff;'>{ctx.vip_name or 'user'}</strong> "
        f"covering {period}.",
        lang,
    )
    hold_lbl = _L("Titular VIP", "VIP holder", lang)
    period_lbl = _L("Período", "Period", lang)
    moves_lbl = _L("Movimientos incluidos", "Movements included", lang)
    outro = _L(
        "Este PDF contiene los saldos iniciales y finales del período, "
        "junto con el detalle de todos los movimientos confirmados/aprobados. "
        "Guarda una copia para conciliaciones y auditoría interna.",
        "This PDF contains opening and closing balances for the period plus "
        "every confirmed/approved movement. Keep a copy for reconciliation "
        "and internal audit.",
        lang,
    )
    footer = (
        f'{_L("Documento generado el", "Document generated on", lang)} '
        f'{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · '
        f'{_L("Emisor", "Issued by", lang)}: {ctx.issuer_name}'
    )
    return f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">{intro}</p>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{hold_lbl}</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{ctx.vip_name or "—"}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{period_lbl}</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{period}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{moves_lbl}</td>
            <td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{ctx.movements_count}</td></tr>
      </table>
      {_ledger_note_block(ctx)}
      <p style="color:#A3A3A3;font-size:13px;line-height:1.6;margin:22px 0 0;">{outro}</p>
      <p style="color:#666;font-size:11px;margin:22px 0 0;">{footer}</p>
    """


def notify_vip_ledger_statement(ctx: VipLedgerEmailContext) -> bool:
    """iter111 — email the VIP ledger PDF statement as attachment.

    Callers pass a `VipLedgerEmailContext`. See the dataclass docstring
    for rationale. Used from `POST /api/vip/ledger/email`, its admin
    twin, and the monthly APScheduler job.
    """
    period = _ledger_period_label(ctx.since, ctx.until)
    subject = _L(
        f"Estado de cuenta VIP · {period} · Resilience Brothers",
        f"VIP ledger statement · {period} · Resilience Brothers", ctx.lang,
    )
    body = _ledger_body_html(ctx, period)
    filename_period = (period.replace(" → ", "_").replace(" ", "_")
                       .replace("→", "_"))
    attachment = {
        "filename": f"vip_ledger_{filename_period}.pdf",
        "content": base64.b64encode(ctx.pdf_bytes).decode("ascii"),
    }
    template = _base_template(
        _L("Estado de cuenta VIP", "VIP ledger statement", ctx.lang),
        body, ctx.lang,
    )
    return _send(ctx.to, subject, template, attachments=[attachment])


def notify_order_approved(order: dict, user: dict) -> bool:
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    subject = _L(f"Tu orden #{order['id'][:8]} fue aprobada",
                 f"Your order #{order['id'][:8]} was approved", lang)
    rows = f"""
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Par", "Pair", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['from_code']} → {order['to_code']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Enviaste", "You sent", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['amount_from']} {order['from_code']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Recibes", "You receive", lang)}</td><td style="padding:6px 0;color:#8B5CF6;font-family:monospace;text-align:right;font-weight:bold;">{order['amount_to']} {order['to_code']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Tasa aplicada", "Applied rate", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['rate_applied']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Comisión", "Commission", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['commission_percent']}%</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Método entrega", "Delivery method", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['delivery_method']}</td></tr>
    """
    note = f'<div style="background:#0a0a0a;border-left:3px solid #8B5CF6;padding:12px 16px;margin-top:20px;"><p style="margin:0;color:#fff;font-size:13px;">{_L("Nota del equipo:", "Team note:", lang)} {order.get("admin_note","")}</p></div>' if order.get("admin_note") else ""
    approved_word = _L("APROBADA", "APPROVED", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{_L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu pago fue verificado por nuestro equipo contable. Tu orden ya está", f"Hi <strong style='color:#fff;'>{name}</strong>, your payment has been verified by our accounting team. Your order is now", lang)} <span style="color:#22C55E;font-weight:bold;">{approved_word}</span>.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
      </table>
      {note}
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L("Procesaremos la entrega según el método seleccionado. Recibirás otra notificación cuando se complete.", "We'll process the delivery via the selected method. You'll receive another notification when it completes.", lang)}</p>
      <a href="{APP_URL}/dashboard/orders" style="display:inline-block;margin-top:16px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{_L("VER ORDEN →", "VIEW ORDER →", lang)}</a>
    """
    return _send(user.get("email", ""), subject, _base_template(_L("Orden aprobada", "Order approved", lang), body, lang))


def notify_order_rejected(order: dict, user: dict) -> bool:
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    subject = _L(f"Tu orden #{order['id'][:8]} requiere atención",
                 f"Your order #{order['id'][:8]} needs attention", lang)
    reason = order.get("admin_note") or _L("Sin nota adicional", "No additional note", lang)
    rejected_word = _L("RECHAZADA", "REJECTED", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{_L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu orden no pudo ser procesada en este momento.", f"Hi <strong style='color:#fff;'>{name}</strong>, your order could not be processed at this time.", lang)}</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Orden", "Order", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">#{order['id'][:8]}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Par", "Pair", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['from_code']} → {order['to_code']}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Monto", "Amount", lang)}</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['amount_from']} {order['from_code']}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Estado", "Status", lang)}</td><td style="padding:6px 0;color:#EF4444;font-family:monospace;text-align:right;font-weight:bold;">{rejected_word}</td></tr>
      </table>
      <div style="background:#0a0a0a;border-left:3px solid #EF4444;padding:12px 16px;margin-top:20px;">
        <p style="margin:0 0 4px;color:#A3A3A3;font-size:12px;text-transform:uppercase;letter-spacing:1px;">{_L("Motivo", "Reason", lang)}</p>
        <p style="margin:0;color:#fff;font-size:13px;">{reason}</p>
      </div>
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L("Si crees que es un error, responde a este correo o crea una nueva orden con la información corregida.", "If you think this is an error, reply to this email or create a new order with corrected information.", lang)}</p>
      <a href="{APP_URL}/dashboard/orders" style="display:inline-block;margin-top:16px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{_L("REVISAR ORDEN →", "REVIEW ORDER →", lang)}</a>
    """
    return _send(user.get("email", ""), subject, _base_template(_L("Orden rechazada", "Order rejected", lang), body, lang))



# ============================================================
# iter196 — Withdrawal & deposit lifecycle emails
# ============================================================
# Client-facing emails at the two moments they care about:
#   • Withdrawal approved  → "En proceso" (staff started the payout)
#   • Withdrawal paid      → "Exitoso"
#   • Deposit received     → "En proceso" (staff will verify)
#   • Deposit confirmed    → "Exitoso"
# Rejections stay push+in-app only (that channel already covers them).
# Every send is wrapped by _send() which persists to email_events for
# delivery-ledger visibility.

def _short(id_: str) -> str:
    """Return a short human-friendly slug for an entity id.

    Deposits use `dep_<12hex>` while withdrawals use raw uuids, so we strip
    the `dep_` / `wd_` prefix (if any) before truncating so both sides of
    the email templates read consistently ("`#a1b2c3d4`" instead of
    "`#dep_a1b2`" vs "`#a1b2c3d4`").
    """
    if not id_:
        return "—"
    core = id_.split("_", 1)[1] if "_" in id_ else id_
    return core[:8]


def _method_label(method: str, lang: str) -> str:
    if method == "cash":
        return _L("Efectivo", "Cash", lang)
    if method == "transfer":
        return _L("Transferencia bancaria", "Bank transfer", lang)
    if method == "crypto":
        return _L("Cripto", "Crypto", lang)
    return method or "—"


def _kv_row(label: str, value: str, accent: str = "#fff", mono: bool = True) -> str:
    font = "monospace" if mono else "inherit"
    return (
        f'<tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{label}</td>'
        f'<td style="padding:6px 0;color:{accent};font-family:{font};text-align:right;">{value}</td></tr>'
    )


def notify_withdrawal_in_progress(w: dict, user: dict) -> bool:
    """Sent when staff flips a withdrawal from `pending` → `approved`."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    wid = _short(w.get("id", ""))
    subject = _L(f"Tu retiro #{wid} está en proceso",
                 f"Your withdrawal #{wid} is being processed", lang)
    method = _method_label(w.get("method", ""), lang)
    amount = w.get("amount_usd", 0)
    currency = w.get("currency") or "USD"
    rows = (
        _kv_row(_L("Retiro", "Withdrawal", lang), f"#{wid}")
        + _kv_row(_L("Método", "Method", lang), method, mono=False)
        + _kv_row(_L("Monto", "Amount", lang), f"{amount} {currency}")
    )
    if w.get("method") == "crypto" and w.get("crypto_network"):
        rows += _kv_row(_L("Red", "Network", lang), w["crypto_network"])
    if w.get("method") == "cash" and w.get("province"):
        rows += _kv_row(_L("Provincia", "Province", lang), w["province"], mono=False)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{_L(
          f"Hola <strong style='color:#fff;'>{name}</strong>, nuestro equipo aprobó tu retiro y ya está ejecutando el pago.",
          f"Hi <strong style='color:#fff;'>{name}</strong>, our team approved your withdrawal and is now executing the payout.",
          lang,
      )}</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Estado", "Status", lang)}</td><td style="padding:6px 0;color:#EAB308;font-family:monospace;text-align:right;font-weight:bold;">{_L("EN PROCESO", "IN PROGRESS", lang)}</td></tr>
      </table>
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L(
          "Recibirás otra notificación cuando el pago se complete. El tiempo depende del método (crypto suele ser inmediato tras confirmación; transferencia y efectivo pueden tomar unas horas hábiles).",
          "You'll get another notification when the payout is complete. Timing depends on the method (crypto is usually instant after confirmation; transfer and cash can take a few business hours).",
          lang,
      )}</p>
      <a href="{APP_URL}/dashboard/vip" style="display:inline-block;margin-top:16px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{_L("VER RETIRO →", "VIEW WITHDRAWAL →", lang)}</a>
    """
    return _send(user.get("email", ""), subject,
                 _base_template(_L("Retiro en proceso", "Withdrawal in progress", lang), body, lang),
                 kind="withdrawal_in_progress")


def _paid_method_rows(w: dict, lang: str) -> str:
    rows = ""
    if w.get("method") == "crypto":
        if w.get("crypto_network"):
            rows += _kv_row(_L("Red", "Network", lang), w["crypto_network"])
        tx_hash = (w.get("payout_tx_hash") or "").strip()
        if tx_hash:
            rows += _kv_row("TxID", tx_hash[:24] + ("…" if len(tx_hash) > 24 else ""))
    if w.get("method") == "cash" and w.get("province"):
        rows += _kv_row(_L("Provincia", "Province", lang), w["province"], mono=False)
    return rows


def _paid_courier_row(w: dict, currency: str, lang: str) -> str:
    if float(w.get("courier_fee_usdt") or 0) <= 0:
        return ""
    return _kv_row(
        _L("Mensajería", "Courier fee", lang),
        (f"-{w.get('courier_fee_currency_amount')} {w.get('courier_fee_currency') or currency} "
         f"({w.get('courier_km')} km ≈ {w.get('courier_fee_usdt')} USDT)"),
        accent="#F59E0B",
    )


def _withdrawal_paid_rows(w: dict, wid: str, lang: str) -> str:
    """Receipt rows of the `paid` email (method-specific bits included)."""
    currency = w.get("currency") or "USD"
    return (
        _kv_row(_L("Retiro", "Withdrawal", lang), f"#{wid}")
        + _kv_row(_L("Método", "Method", lang), _method_label(w.get("method", ""), lang), mono=False)
        + _kv_row(_L("Monto pagado", "Paid amount", lang),
                  f"{w.get('amount_usd', 0)} {currency}", accent="#22C55E")
        + _paid_method_rows(w, lang)
        + _paid_courier_row(w, currency, lang)
    )


def notify_withdrawal_paid(w: dict, user: dict) -> bool:
    """Sent when staff flips a withdrawal from `approved` → `paid`."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    wid = _short(w.get("id", ""))
    subject = _L(f"Retiro #{wid} exitoso",
                 f"Withdrawal #{wid} successful", lang)
    rows = _withdrawal_paid_rows(w, wid, lang)
    note = ""
    if w.get("admin_note"):
        note = (f'<div style="background:#0a0a0a;border-left:3px solid #22C55E;padding:12px 16px;'
                f'margin-top:20px;"><p style="margin:0;color:#fff;font-size:13px;">'
                f'{_L("Nota del equipo:", "Team note:", lang)} {w["admin_note"]}</p></div>')
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{_L(
          f"Hola <strong style='color:#fff;'>{name}</strong>, tu retiro fue procesado con éxito.",
          f"Hi <strong style='color:#fff;'>{name}</strong>, your withdrawal was successfully processed.",
          lang,
      )} <span style="color:#22C55E;font-weight:bold;">{_L("EXITOSO", "SUCCESSFUL", lang)}</span>.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
      </table>
      {note}
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L(
          "Guarda este correo como comprobante. Si algo no coincide, responde a este mensaje y lo revisamos.",
          "Keep this email as proof of payment. If anything doesn't match, reply to this message and we'll review it.",
          lang,
      )}</p>
      <a href="{APP_URL}/dashboard/vip" style="display:inline-block;margin-top:16px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{_L("VER DETALLE →", "VIEW DETAILS →", lang)}</a>
    """
    return _send(user.get("email", ""), subject,
                 _base_template(_L("Retiro exitoso", "Withdrawal successful", lang), body, lang),
                 kind="withdrawal_paid")


def notify_deposit_received(d: dict, user: dict) -> bool:
    """Sent immediately when a client creates a deposit (status `pending`)."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    did = _short(d.get("id", ""))
    subject = _L(f"Tu depósito #{did} está en proceso",
                 f"Your deposit #{did} is being processed", lang)
    method = _method_label(d.get("method", ""), lang)
    amount = d.get("amount", 0)
    currency = d.get("currency") or "USD"
    rows = (
        _kv_row(_L("Depósito", "Deposit", lang), f"#{did}")
        + _kv_row(_L("Método", "Method", lang), method, mono=False)
        + _kv_row(_L("Monto", "Amount", lang), f"{amount} {currency}")
    )
    if d.get("method") == "crypto" and d.get("network"):
        rows += _kv_row(_L("Red", "Network", lang), d["network"])
    if d.get("method") == "cash" and d.get("cash_mode"):
        cash_label = _L("Recogida a domicilio", "Courier pickup", lang) if d["cash_mode"] == "courier" else _L("En oficina", "At office", lang)
        rows += _kv_row(_L("Modo", "Mode", lang), cash_label, mono=False)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{_L(
          f"Hola <strong style='color:#fff;'>{name}</strong>, recibimos tu depósito y nuestro equipo lo está verificando.",
          f"Hi <strong style='color:#fff;'>{name}</strong>, we received your deposit and our team is verifying it.",
          lang,
      )}</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Estado", "Status", lang)}</td><td style="padding:6px 0;color:#EAB308;font-family:monospace;text-align:right;font-weight:bold;">{_L("EN PROCESO", "IN PROGRESS", lang)}</td></tr>
      </table>
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L(
          "Te notificaremos por correo cuando el depósito sea confirmado y tu saldo esté acreditado. Normalmente en horas hábiles.",
          "We'll email you when the deposit is confirmed and your balance is credited. Usually within business hours.",
          lang,
      )}</p>
      <a href="{APP_URL}/dashboard/vip" style="display:inline-block;margin-top:16px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{_L("VER DEPÓSITO →", "VIEW DEPOSIT →", lang)}</a>
    """
    return _send(user.get("email", ""), subject,
                 _base_template(_L("Depósito en proceso", "Deposit in progress", lang), body, lang),
                 kind="deposit_received")


def notify_deposit_confirmed(d: dict, user: dict) -> bool:
    """Sent when staff confirms a deposit (status `confirmed`)."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    did = _short(d.get("id", ""))
    subject = _L(f"Depósito #{did} exitoso",
                 f"Deposit #{did} successful", lang)
    method = _method_label(d.get("method", ""), lang)
    amount = d.get("amount", 0)
    currency = d.get("currency") or "USD"
    rows = (
        _kv_row(_L("Depósito", "Deposit", lang), f"#{did}")
        + _kv_row(_L("Método", "Method", lang), method, mono=False)
        + _kv_row(_L("Monto acreditado", "Credited amount", lang), f"{amount} {currency}", accent="#22C55E")
    )
    if d.get("method") == "crypto" and d.get("network"):
        rows += _kv_row(_L("Red", "Network", lang), d["network"])
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{_L(
          f"Hola <strong style='color:#fff;'>{name}</strong>, tu depósito fue verificado y acreditado en tu saldo.",
          f"Hi <strong style='color:#fff;'>{name}</strong>, your deposit was verified and credited to your balance.",
          lang,
      )} <span style="color:#22C55E;font-weight:bold;">{_L("EXITOSO", "SUCCESSFUL", lang)}</span>.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
      </table>
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L(
          "Ya puedes usar el saldo para operar en el mercado o solicitar un retiro.",
          "You can now use the balance to trade in the market or request a withdrawal.",
          lang,
      )}</p>
      <a href="{APP_URL}/dashboard/vip" style="display:inline-block;margin-top:16px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{_L("VER SALDO →", "VIEW BALANCE →", lang)}</a>
    """
    return _send(user.get("email", ""), subject,
                 _base_template(_L("Depósito exitoso", "Deposit successful", lang), body, lang),
                 kind="deposit_confirmed")


def notify_deposit_rejected(d: dict, user: dict, admin_note: str = "") -> bool:
    """Sent when staff rejects a deposit (status `rejected`)."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    did = _short(d.get("id", ""))
    subject = _L(f"Depósito #{did} rechazado",
                 f"Deposit #{did} rejected", lang)
    method = _method_label(d.get("method", ""), lang)
    amount = d.get("amount", 0)
    currency = d.get("currency") or "USD"
    rows = (
        _kv_row(_L("Depósito", "Deposit", lang), f"#{did}")
        + _kv_row(_L("Método", "Method", lang), method, mono=False)
        + _kv_row(_L("Monto", "Amount", lang), f"{amount} {currency}")
        + f'<tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">{_L("Estado", "Status", lang)}</td><td style="padding:6px 0;color:#EF4444;font-family:monospace;text-align:right;font-weight:bold;">{_L("RECHAZADO", "REJECTED", lang)}</td></tr>'
    )
    note_html = _reject_note_html(admin_note or d.get("admin_note") or "", lang)
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{_L(
          f"Hola <strong style='color:#fff;'>{name}</strong>, tu depósito fue revisado y no pudo ser aprobado.",
          f"Hi <strong style='color:#fff;'>{name}</strong>, your deposit was reviewed and could not be approved.",
          lang,
      )}</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
      </table>
      {note_html}
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L(
          "Si crees que se trata de un error, corrige el problema indicado y crea un nuevo depósito, o responde a este correo para contactar al equipo.",
          "If you believe this is an error, fix the indicated issue and create a new deposit, or reply to this email to contact the team.",
          lang,
      )}</p>
      <a href="{APP_URL}/dashboard/vip" style="display:inline-block;margin-top:16px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{_L("VER DEPÓSITOS →", "VIEW DEPOSITS →", lang)}</a>
    """
    return _send(user.get("email", ""), subject,
                 _base_template(_L("Depósito rechazado", "Deposit rejected", lang), body, lang),
                 kind="deposit_rejected")


_CAPITAL_METHOD_LABELS = {
    "bank_transfer": ("Transferencia bancaria", "Bank transfer"),
    "crypto": ("Cripto (USDT)", "Crypto (USDT)"),
    "zelle": ("Zelle", "Zelle"),
    "other": ("Otro método", "Other method"),
}


def _status_badge(ok: bool, ok_es: str, ok_en: str, bad_es: str, bad_en: str,
                  lang: str) -> str:
    color = "#22C55E" if ok else "#EF4444"
    label = _L(ok_es, ok_en, lang) if ok else _L(bad_es, bad_en, lang)
    return f'<span style="color:{color};font-weight:bold;">{label}</span>'


def _reject_note_html(note: str, lang: str) -> str:
    note = (note or "").strip()
    if not note:
        return ""
    return f"""
      <div style="margin-top:16px;border-left:3px solid #EF4444;background:#1a0d0d;padding:12px 16px;">
        <p style="margin:0;color:#A3A3A3;font-size:12px;text-transform:uppercase;letter-spacing:1px;">{_L("Motivo del rechazo", "Rejection reason", lang)}</p>
        <p style="margin:6px 0 0;color:#fff;font-size:14px;">{note}</p>
      </div>"""


def _decision_body(intro: str, status_html: str, rows: str, note_html: str,
                   extra: str, cta_label: str, cta_margin: int = 24) -> str:
    """Shared layout of the approve/reject decision emails: intro + status,
    receipt table, optional rejection note, optional extra, CTA button."""
    return f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">{intro} {status_html}.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
      </table>
      {note_html}
      {extra}
      <a href="{APP_URL}/dashboard/vip" style="display:inline-block;margin-top:{cta_margin}px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">{cta_label}</a>
    """


def _capital_deposit_texts(approved: bool, did: str, name: str, lang: str) -> tuple:
    """(subject, intro) for the capital-deposit decision email."""
    if approved:
        return (_L(f"Depósito de capital #{did} confirmado",
                   f"Capital deposit #{did} confirmed", lang),
                _L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu depósito de capital fue verificado y acreditado en tu saldo.",
                   f"Hi <strong style='color:#fff;'>{name}</strong>, your capital deposit was verified and credited to your balance.",
                   lang))
    return (_L(f"Depósito de capital #{did} rechazado",
               f"Capital deposit #{did} rejected", lang),
            _L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu depósito de capital fue revisado y no pudo ser aprobado.",
               f"Hi <strong style='color:#fff;'>{name}</strong>, your capital deposit was reviewed and could not be approved.",
               lang))


def _capital_deposit_rows(d: dict, approved: bool, did: str, method: str,
                          lang: str) -> str:
    rows = (
        _kv_row(_L("Depósito de capital", "Capital deposit", lang), f"#{did}")
        + _kv_row(_L("Método", "Method", lang), method, mono=False)
        + _kv_row(_L("Monto", "Amount", lang),
                  f"{d.get('amount', 0)} {d.get('currency') or 'USDT'}",
                  accent="#22C55E" if approved else "#fff")
    )
    if approved and d.get("balance_delta_usdt"):
        rows += _kv_row(_L("Acreditado (USDT)", "Credited (USDT)", lang),
                        f"{round(float(d['balance_delta_usdt']), 2)} USDT", accent="#22C55E")
    return rows


def notify_capital_deposit_decision(d: dict, user: dict, approved: bool,
                                    admin_note: str = "") -> bool:
    """Sent when staff confirms/rejects a VIP capital deposit."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    did = _short(d.get("id", ""))
    m = _CAPITAL_METHOD_LABELS.get(d.get("method", ""), None)
    method = _L(m[0], m[1], lang) if m else (d.get("method") or "—")
    subject, intro = _capital_deposit_texts(approved, did, name, lang)
    status_html = _status_badge(approved, "CONFIRMADO", "CONFIRMED",
                                "RECHAZADO", "REJECTED", lang)
    rows = _capital_deposit_rows(d, approved, did, method, lang)
    note_html = "" if approved else _reject_note_html(
        admin_note or d.get("admin_note") or "", lang)
    body = _decision_body(intro, status_html, rows, note_html, "",
                          _L("VER MI SALDO →", "VIEW MY BALANCE →", lang))
    title = _L("Depósito de capital", "Capital deposit", lang)
    return _send(user.get("email", ""), subject, _base_template(title, body, lang),
                 kind="capital_deposit_confirmed" if approved else "capital_deposit_rejected")


def _settlement_texts(approved: bool, sid: str, name: str, lang: str) -> tuple:
    """(subject, intro) for the settlement decision email."""
    if approved:
        return (_L(f"Cobro/liquidación #{sid} confirmado",
                   f"Settlement #{sid} confirmed", lang),
                _L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu operación de cobro/liquidación fue procesada.",
                   f"Hi <strong style='color:#fff;'>{name}</strong>, your settlement was processed.",
                   lang))
    return (_L(f"Cobro/liquidación #{sid} rechazado",
               f"Settlement #{sid} rejected", lang),
            _L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu solicitud de cobro fue revisada y no pudo ser aprobada.",
               f"Hi <strong style='color:#fff;'>{name}</strong>, your settlement request was reviewed and could not be approved.",
               lang))


def _settlement_rows(s: dict, approved: bool, sid: str, lang: str) -> str:
    dir_label = (_L("Cobro (pago hacia ti)", "Payout (payment to you)", lang)
                 if (s.get("direction") or "payout") == "payout"
                 else _L("Liquidación de deuda", "Debt settlement", lang))
    rows = (
        _kv_row(_L("Operación", "Operation", lang), f"#{sid}")
        + _kv_row(_L("Tipo", "Type", lang), dir_label, mono=False)
        + _kv_row(_L("Monto", "Amount", lang),
                  f"{s.get('amount', 0)} {s.get('currency') or 'USDT'}",
                  accent="#22C55E" if approved else "#fff")
    )
    if s.get("settlement_method"):
        rows += _kv_row(_L("Método", "Method", lang), str(s["settlement_method"]), mono=False)
    return rows


def notify_settlement_decision(s: dict, user: dict, approved: bool,
                               admin_note: str = "") -> bool:
    """Sent when staff confirms/rejects a VIP settlement (cobro/liquidación)."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    sid = _short(s.get("id", ""))
    subject, intro = _settlement_texts(approved, sid, name, lang)
    status_html = _status_badge(approved, "CONFIRMADO", "CONFIRMED",
                                "RECHAZADO", "REJECTED", lang)
    rows = _settlement_rows(s, approved, sid, lang)
    note_html = "" if approved else _reject_note_html(
        admin_note or s.get("admin_note") or "", lang)
    body = _decision_body(intro, status_html, rows, note_html, "",
                          _L("VER MI HISTORIAL →", "VIEW MY HISTORY →", lang))
    title = _L("Cobro / Liquidación", "Settlement", lang)
    return _send(user.get("email", ""), subject, _base_template(title, body, lang),
                 kind="settlement_confirmed" if approved else "settlement_rejected")


def _capital_request_texts(approved: bool, rid: str, name: str, lang: str) -> tuple:
    """(subject, intro) for the capital-request decision email."""
    if approved:
        return (_L(f"Solicitud de capital #{rid} aprobada",
                   f"Capital request #{rid} approved", lang),
                _L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu solicitud de fondos operativos fue aprobada y el monto ya está acreditado en tu saldo.",
                   f"Hi <strong style='color:#fff;'>{name}</strong>, your working-capital request was approved and the amount is credited to your balance.",
                   lang))
    return (_L(f"Solicitud de capital #{rid} rechazada",
               f"Capital request #{rid} rejected", lang),
            _L(f"Hola <strong style='color:#fff;'>{name}</strong>, tu solicitud de fondos operativos fue revisada y no pudo ser aprobada.",
               f"Hi <strong style='color:#fff;'>{name}</strong>, your working-capital request was reviewed and could not be approved.",
               lang))


def _capital_request_rows(r: dict, approved: bool, rid: str, lang: str) -> str:
    rows = (
        _kv_row(_L("Solicitud", "Request", lang), f"#{rid}")
        + _kv_row(_L("Monto", "Amount", lang),
                  f"{r.get('amount', 0)} {r.get('currency_code') or 'USDT'}",
                  accent="#22C55E" if approved else "#fff")
    )
    if approved and r.get("discount_pct") is not None:
        rows += _kv_row(_L("Descuento por orden", "Per-order discount", lang),
                        f"{r['discount_pct']}%")
    return rows


def notify_capital_request_decision(r: dict, user: dict, approved: bool) -> bool:
    """Sent when staff approves (disburses) or rejects a VIP capital request."""
    lang = user.get("preferred_language") or "es"
    name = user.get("name") or _L("Cliente", "Customer", lang)
    rid = _short(r.get("id", ""))
    subject, intro = _capital_request_texts(approved, rid, name, lang)
    status_html = _status_badge(approved, "APROBADA Y DESEMBOLSADA", "APPROVED & DISBURSED",
                                "RECHAZADA", "REJECTED", lang)
    rows = _capital_request_rows(r, approved, rid, lang)
    note_html = "" if approved else _reject_note_html(r.get("reject_reason") or "", lang)
    extra = ""
    if approved:
        extra = f"""
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">{_L(
          "El monto se descontará automáticamente de tus próximas órdenes acumuladas según el porcentaje acordado.",
          "The amount will be automatically repaid from your upcoming accumulated orders at the agreed percentage.",
          lang,
      )}</p>"""
    body = _decision_body(intro, status_html, rows, note_html, extra,
                          _L("VER MI SALDO →", "VIEW MY BALANCE →", lang),
                          cta_margin=16)
    title = _L("Solicitud de capital", "Capital request", lang)
    return _send(user.get("email", ""), subject, _base_template(title, body, lang),
                 kind="capital_request_disbursed" if approved else "capital_request_rejected")
