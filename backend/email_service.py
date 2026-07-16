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
from datetime import datetime, timezone
import resend

logger = logging.getLogger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")
SENDER = os.environ.get("EMAIL_SENDER", "Resilience Brothers <onboarding@resend.dev>")
REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "")
APP_URL = os.environ.get("APP_PUBLIC_URL", "")


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


def _send(to: str, subject: str, html: str, attachments: list = None) -> bool:
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set, skipping email")
        return False
    if not to:
        return False
    try:
        params = {"from": SENDER, "to": [to], "subject": subject, "html": html}
        if REPLY_TO:
            params["reply_to"] = REPLY_TO
        if attachments:
            params["attachments"] = attachments
        resp = resend.Emails.send(params)
        logger.info(f"Email sent to {to}: id={resp.get('id')}")
        return True
    except Exception as e:
        logger.error(f"Resend email failed for {to}: {e}")
        return False


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


# ============== iter17 — email verification & password reset ==============

def _app_url() -> str:
    return APP_URL.rstrip("/") if APP_URL else "https://p2p.resiliencebrothers.com"

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
                 _base_template(_L("Verifica tu cuenta", "Verify your account", lang), body, lang))


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
                 _base_template(_L("Recuperar contraseña", "Recover password", lang), body, lang))


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
