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


def send_push(subscription: dict, payload: dict) -> bool:
    """Send a single web push notification. Returns False if subscription is dead/invalid."""
    if not _PRIVATE_KEY or not subscription:
        return False
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=86400,
        )
        return True
    except WebPushException as e:
        # 410 Gone or 404 = subscription expired/removed
        status = getattr(e.response, "status_code", None) if e.response else None
        if status in (404, 410):
            logger.info(f"Push subscription expired (status {status})")
            return False
        logger.error(f"Push failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Push exception: {e}")
        return False


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
