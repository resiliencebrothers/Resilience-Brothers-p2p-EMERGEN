"""Web Push notifications via VAPID."""
import os
import json
import logging
from pathlib import Path
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_PATH = os.environ.get("VAPID_PRIVATE_PATH", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:noreply@resiliencebrothers.com")
APP_URL = os.environ.get("APP_PUBLIC_URL", "")

_PRIVATE_KEY = None
if VAPID_PRIVATE_PATH and Path(VAPID_PRIVATE_PATH).exists():
    _PRIVATE_KEY = Path(VAPID_PRIVATE_PATH).read_text()


def send_push(subscription: dict, payload: dict) -> str:
    """Send a single web push notification.
    Returns: 'ok' on success, 'dead' if subscription is expired/gone (delete it),
    'transient' for network/encryption errors (keep subscription, retry later),
    'disabled' if VAPID key not configured.
    """
    if not _PRIVATE_KEY:
        return "disabled"
    if not subscription:
        return "dead"
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=86400,
        )
        return "ok"
    except WebPushException as e:
        status = getattr(e.response, "status_code", None) if e.response else None
        if status in (404, 410):
            logger.info(f"Push subscription expired (status {status})")
            return "dead"
        logger.error(f"Push transient failure (status {status}): {e}")
        return "transient"
    except Exception as e:
        logger.error(f"Push exception: {e}")
        return "transient"


def build_order_approved_payload(order: dict) -> dict:
    return {
        "title": f"Orden #{order['id'][:8]} aprobada ✓",
        "body": f"{order['amount_to']} {order['to_code']} listos para entregar.",
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"order-{order['id']}",
        "url": f"{APP_URL}/dashboard/orders" if APP_URL else "/dashboard/orders",
    }


def build_order_rejected_payload(order: dict) -> dict:
    note = (order.get("admin_note") or "")[:80]
    return {
        "title": f"Orden #{order['id'][:8]} rechazada",
        "body": note or "Por favor revisa los detalles desde tu dashboard.",
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"order-{order['id']}",
        "url": f"{APP_URL}/dashboard/orders" if APP_URL else "/dashboard/orders",
    }


# ============================================================
# iter30 — generic per-user push delivery used by routes/notifications.py
# ============================================================

async def send_push_to_user(db, user_id: str, payload: dict) -> None:
    """Send `payload` to every active push subscription registered for `user_id`.
    Silently prunes dead subscriptions. Best-effort — never raises."""
    try:
        subs = await db.push_subscriptions.find(
            {"user_id": user_id}, {"_id": 0}
        ).to_list(50)
        if not subs:
            return
        dead_ids = []
        for s in subs:
            result = send_push(s.get("subscription"), payload)
            if result == "dead":
                dead_ids.append(s.get("id"))
        if dead_ids:
            await db.push_subscriptions.delete_many({"id": {"$in": dead_ids}})
    except Exception as e:
        logger.error(f"send_push_to_user({user_id}) failed: {e}")


def build_new_pending_user_payload(target_user: dict) -> dict:
    name = target_user.get("name") or target_user.get("email") or "Usuario"
    phone = target_user.get("phone") or "-"
    return {
        "title": "Nuevo usuario pendiente de verificación",
        "body": f"{name} ({phone}). Verifica o rechaza desde Admin → Usuarios.",
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"pending-{target_user.get('user_id', 'x')}",
        "url": f"{APP_URL}/admin/users" if APP_URL else "/admin/users",
    }


def build_phone_verified_payload(target_user: dict) -> dict:
    return {
        "title": "¡Tu cuenta está activa! ✓",
        "body": "Hemos verificado tu teléfono. Ya puedes operar en la plataforma.",
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"verified-{target_user.get('user_id', 'x')}",
        "url": f"{APP_URL}/dashboard" if APP_URL else "/dashboard",
    }


def build_phone_rejected_payload(target_user: dict, reason: str) -> dict:
    return {
        "title": "Verificación rechazada",
        "body": (reason or "Tu teléfono no pudo ser verificado. Contacta a soporte.")[:140],
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"rejected-{target_user.get('user_id', 'x')}",
        "url": f"{APP_URL}/dashboard" if APP_URL else "/dashboard",
    }

