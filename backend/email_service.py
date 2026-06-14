"""Email notifications via Resend."""
import os
import logging
import resend

logger = logging.getLogger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")
SENDER = os.environ.get("EMAIL_SENDER", "Resilience Brothers <onboarding@resend.dev>")
REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "")
APP_URL = os.environ.get("APP_PUBLIC_URL", "")


def _base_template(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:'Helvetica Neue',Arial,sans-serif;color:#FFFFFF;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0A0A0A;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#141414;border:1px solid rgba(255,255,255,0.08);">
        <tr><td style="padding:24px 32px;border-bottom:1px solid rgba(255,255,255,0.08);">
          <table width="100%"><tr>
            <td><span style="display:inline-block;background:#EAB308;color:#000;font-weight:900;padding:6px 10px;letter-spacing:0.5px;">RB</span>
              <span style="font-weight:800;color:#fff;margin-left:8px;font-size:14px;letter-spacing:1px;">RESILIENCE BROTHERS</span></td>
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


def _send(to: str, subject: str, html: str) -> bool:
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set, skipping email")
        return False
    if not to:
        return False
    try:
        params = {"from": SENDER, "to": [to], "subject": subject, "html": html}
        if REPLY_TO:
            params["reply_to"] = REPLY_TO
        resp = resend.Emails.send(params)
        logger.info(f"Email sent to {to}: id={resp.get('id')}")
        return True
    except Exception as e:
        logger.error(f"Resend email failed for {to}: {e}")
        return False


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
