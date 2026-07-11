"""Email notifications via Resend."""
import os
import base64
import logging
import resend

logger = logging.getLogger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")
SENDER = os.environ.get("EMAIL_SENDER", "Resilience Brothers <onboarding@resend.dev>")
REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "")
APP_URL = os.environ.get("APP_PUBLIC_URL", "")


def _base_template(title: str, body_html: str) -> str:
    logo_url = f"{APP_URL}/branding/logo-300.png" if APP_URL else ""
    logo_html = f'<img src="{logo_url}" alt="Resilience Brothers" width="48" height="48" style="display:block;border:0;outline:none;">' if logo_url else '<span style="display:inline-block;background:#EAB308;color:#000;font-weight:900;padding:6px 10px;letter-spacing:0.5px;">RB</span>'
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
            <td align="right"><span style="font-size:10px;color:#A3A3A3;letter-spacing:2px;text-transform:uppercase;">P2P · Notification</span></td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:32px;">
          <h1 style="font-size:28px;line-height:1.1;margin:0 0 16px;color:#fff;font-weight:900;letter-spacing:-0.5px;">{title}</h1>
          {body_html}
        </td></tr>
        <tr><td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.08);background:#0c0c0c;">
          <p style="margin:0;color:#A3A3A3;font-size:12px;line-height:1.5;">Este mensaje fue enviado por Resilience Brothers · Plataforma P2P de comercio global. Si tienes preguntas, responde directamente a este correo.</p>
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
      <p style="margin:18px 0 6px;color:#EAB308;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Top actores</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:12px 20px;">
        {top_actors_html}
      </table>
      <p style="margin:22px 0 6px;color:#EAB308;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Firma de integridad</p>
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

def notify_email_change_code(to: str, name: str, code: str) -> bool:
    """iter55.20 — send OTP to the NEW email during profile email change."""
    subject = "Confirma tu nuevo email · Resilience Brothers"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">
        Hola {name or 'usuario'} — recibimos una solicitud para actualizar tu email
        a esta dirección. Ingresa el siguiente código en la plataforma para confirmar.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(234,179,8,0.4);padding:24px;text-align:center;">
        <div style="color:#EAB308;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">Código de confirmación</div>
        <div style="color:#fff;font-family:monospace;font-size:32px;letter-spacing:8px;font-weight:bold;">{code}</div>
      </div>
      <p style="color:#A3A3A3;font-size:13px;line-height:1.6;margin:22px 0 0;">
        El código expira en 15 minutos. Si no solicitaste este cambio, ignora
        este mensaje — tu email actual seguirá activo.
      </p>
    """
    return _send(to, subject, _base_template("Confirma tu nuevo email", body))


def notify_email_change_alert(to: str, name: str, new_email_masked: str) -> bool:
    """iter55.20 — heads-up to the OLD email so silent takeovers get noticed."""
    subject = "Alerta de seguridad · Cambio de email en curso"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        Hola {name or 'usuario'} — se solicitó cambiar el email de tu cuenta a
        <strong style="color:#fff;font-family:monospace;">{new_email_masked}</strong>.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(239,68,68,0.4);padding:18px;">
        <p style="margin:0 0 10px;color:#EF4444;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">¿No fuiste tú?</p>
        <p style="margin:0;color:#A3A3A3;font-size:13px;line-height:1.6;">
          Si <strong style="color:#fff;">no</strong> reconoces esta solicitud, cambia
          tu contraseña de inmediato y contacta al equipo. El cambio no se aplicará
          hasta que se confirme el código enviado al nuevo email.
        </p>
      </div>
      <p style="color:#A3A3A3;font-size:12px;margin:22px 0 0;">
        Si sí fuiste tú, ignora este correo — recibirás una notificación cuando el cambio se complete.
      </p>
    """
    return _send(to, subject, _base_template("Alerta de seguridad", body))


def notify_email_change_success(to: str, name: str, other_email_masked: str) -> bool:
    """iter55.20 — post-change confirmation, sent to both old and new inbox."""
    subject = "Email actualizado · Resilience Brothers"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        Hola {name or 'usuario'} — el email de tu cuenta fue actualizado correctamente.
        La otra dirección asociada es <strong style="color:#fff;font-family:monospace;">{other_email_masked}</strong>.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(34,197,94,0.4);padding:18px;">
        <p style="margin:0;color:#22C55E;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">Cambio aplicado</p>
      </div>
      <p style="color:#A3A3A3;font-size:13px;margin:22px 0 0;line-height:1.6;">
        A partir de ahora recibirás todos los avisos en tu email actualizado.
        Si no reconoces este cambio, contacta al equipo de soporte de inmediato.
      </p>
    """
    return _send(to, subject, _base_template("Email actualizado", body))


def notify_phone_change_approved(to: str, name: str, new_phone_masked: str) -> bool:
    """iter55.20b — inform the client their phone-change request was approved."""
    subject = "Tu nuevo teléfono fue verificado · Resilience Brothers"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        Hola {name or 'usuario'} — el equipo aprobó tu solicitud de cambio de
        teléfono. A partir de ahora recibirás los avisos SMS en
        <strong style="color:#fff;font-family:monospace;">{new_phone_masked}</strong>.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(34,197,94,0.4);padding:18px;">
        <p style="margin:0;color:#22C55E;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">Cambio aplicado</p>
      </div>
      <p style="color:#A3A3A3;font-size:13px;line-height:1.6;margin:22px 0 0;">
        Si <strong style="color:#fff;">no</strong> reconoces este cambio, contacta al equipo de
        soporte de inmediato — el número recién verificado podría permitir
        recuperar la cuenta.
      </p>
    """
    return _send(to, subject, _base_template("Teléfono verificado", body))


def notify_phone_change_rejected(to: str, name: str, new_phone_masked: str,
                                  reason: str) -> bool:
    """iter55.20b — inform the client their phone-change request was rejected."""
    subject = "Solicitud de cambio de teléfono rechazada · Resilience Brothers"
    safe_reason = (reason or "").strip()[:400] or "Sin motivo especificado"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 20px;">
        Hola {name or 'usuario'} — el equipo revisó tu solicitud de cambio de
        teléfono a <strong style="color:#fff;font-family:monospace;">{new_phone_masked}</strong>
        y decidió no aplicarlo por ahora. Tu número actual sigue activo.
      </p>
      <div style="background:#0a0a0a;border:1px solid rgba(239,68,68,0.4);padding:18px;">
        <p style="margin:0 0 8px;color:#EF4444;font-size:12px;text-transform:uppercase;letter-spacing:2px;font-weight:bold;">Motivo</p>
        <p style="margin:0;color:#fff;font-size:13px;line-height:1.6;">{safe_reason}</p>
      </div>
      <p style="color:#A3A3A3;font-size:13px;line-height:1.6;margin:22px 0 0;">
        Puedes volver a solicitar el cambio desde tu perfil aportando la
        documentación de respaldo que el equipo indique, o contactar a soporte
        para cualquier duda.
      </p>
    """
    return _send(to, subject, _base_template("Cambio de teléfono rechazado", body))


def notify_email_verification(to: str, name: str, token: str) -> bool:
    link = f"{_app_url()}/auth/verify-email/{token}"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.7;margin:0 0 24px;">
        ¡Hola {name or 'usuario'}! 👋<br><br>
        Gracias por crear tu cuenta en Resilience Brothers. Para empezar a operar
        necesitamos confirmar que este correo te pertenece.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:8px 0 24px;">
          <a href="{link}" style="background:#EAB308;color:#000;text-decoration:none;
             padding:14px 36px;font-weight:bold;font-family:Arial;letter-spacing:1px;
             display:inline-block;">VERIFICAR MI EMAIL</a>
        </td></tr>
      </table>
      <p style="color:#666;font-size:12px;margin:0 0 6px;">El enlace expira en 24 horas.</p>
      <p style="color:#666;font-size:11px;word-break:break-all;">O copia: {link}</p>
    """
    return _send(to, "Verifica tu correo · Resilience Brothers",
                 _base_template("Verifica tu cuenta", body))


def notify_password_reset(to: str, name: str, token: str) -> bool:
    link = f"{_app_url()}/auth/reset-password/{token}"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.7;margin:0 0 24px;">
        Hola {name or 'usuario'},<br><br>
        Recibimos una solicitud para restablecer la contraseña de tu cuenta en
        Resilience Brothers. Si fuiste tú, haz clic abajo. Si no, ignora este correo.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:8px 0 24px;">
          <a href="{link}" style="background:#EAB308;color:#000;text-decoration:none;
             padding:14px 36px;font-weight:bold;font-family:Arial;letter-spacing:1px;
             display:inline-block;">CREAR NUEVA CONTRASEÑA</a>
        </td></tr>
      </table>
      <p style="color:#666;font-size:12px;margin:0 0 6px;">El enlace expira en 2 horas.</p>
      <p style="color:#666;font-size:11px;word-break:break-all;">O copia: {link}</p>
    """
    return _send(to, "Restablecer contraseña · Resilience Brothers",
                 _base_template("Recuperar contraseña", body))


def notify_order_approved(order: dict, user: dict) -> bool:
    name = user.get("name") or "Cliente"
    subject = f"Tu orden #{order['id'][:8]} fue aprobada"
    rows = f"""
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Par</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['from_code']} → {order['to_code']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Enviaste</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['amount_from']} {order['from_code']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Recibes</td><td style="padding:6px 0;color:#EAB308;font-family:monospace;text-align:right;font-weight:bold;">{order['amount_to']} {order['to_code']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Tasa aplicada</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['rate_applied']}</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Comisión</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['commission_percent']}%</td></tr>
      <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Método entrega</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['delivery_method']}</td></tr>
    """
    note = f'<div style="background:#0a0a0a;border-left:3px solid #EAB308;padding:12px 16px;margin-top:20px;"><p style="margin:0;color:#fff;font-size:13px;">Nota del equipo: {order.get("admin_note","")}</p></div>' if order.get("admin_note") else ""
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">Hola <strong style="color:#fff;">{name}</strong>, tu pago fue verificado por nuestro equipo contable. Tu orden ya está <span style="color:#22C55E;font-weight:bold;">APROBADA</span>.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        {rows}
      </table>
      {note}
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">Procesaremos la entrega según el método seleccionado. Recibirás otra notificación cuando se complete.</p>
      <a href="{APP_URL}/dashboard/orders" style="display:inline-block;margin-top:16px;background:#EAB308;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">VER ORDEN →</a>
    """
    return _send(user.get("email", ""), subject, _base_template("Orden aprobada", body))


def notify_order_rejected(order: dict, user: dict) -> bool:
    name = user.get("name") or "Cliente"
    subject = f"Tu orden #{order['id'][:8]} requiere atención"
    reason = order.get("admin_note") or "Sin nota adicional"
    body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 24px;">Hola <strong style="color:#fff;">{name}</strong>, tu orden no pudo ser procesada en este momento.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid rgba(255,255,255,0.08);padding:20px;">
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Orden</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">#{order['id'][:8]}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Par</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['from_code']} → {order['to_code']}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Monto</td><td style="padding:6px 0;color:#fff;font-family:monospace;text-align:right;">{order['amount_from']} {order['from_code']}</td></tr>
        <tr><td style="padding:6px 0;color:#A3A3A3;font-size:13px;">Estado</td><td style="padding:6px 0;color:#EF4444;font-family:monospace;text-align:right;font-weight:bold;">RECHAZADA</td></tr>
      </table>
      <div style="background:#0a0a0a;border-left:3px solid #EF4444;padding:12px 16px;margin-top:20px;">
        <p style="margin:0 0 4px;color:#A3A3A3;font-size:12px;text-transform:uppercase;letter-spacing:1px;">Motivo</p>
        <p style="margin:0;color:#fff;font-size:13px;">{reason}</p>
      </div>
      <p style="margin:24px 0 8px;color:#A3A3A3;font-size:13px;">Si crees que es un error, responde a este correo o crea una nueva orden con la información corregida.</p>
      <a href="{APP_URL}/dashboard/orders" style="display:inline-block;margin-top:16px;background:#EAB308;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">REVISAR ORDEN →</a>
    """
    return _send(user.get("email", ""), subject, _base_template("Orden rechazada", body))
