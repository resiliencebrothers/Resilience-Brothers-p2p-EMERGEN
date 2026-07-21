"""Web Push notifications via VAPID.

Localised: every `build_*_payload()` helper now accepts an optional `lang`
argument and pulls its title/body from `services.notification_i18n.CATALOG`.
Callers pass the recipient's `preferred_language` (typically resolved via
`resolve_lang(db, user_id)` at the callsite). When not provided the service
falls back to the platform default (Spanish) for backwards compatibility.
"""
import os
import json
import logging
from pathlib import Path
from typing import Optional
from pywebpush import webpush, WebPushException

from services.notification_i18n import t as _t, get_field

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


def _order_short(order: dict) -> str:
    return order["id"][:8]


def build_order_approved_payload(order: dict, lang: Optional[str] = None) -> dict:
    short_id = _order_short(order)
    return {
        "title": _t("order_approved", lang, "push_title", short_id=short_id),
        "body": _t(
            "order_approved", lang, "push_body",
            amt=order["amount_to"], code=order["to_code"],
        ),
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"order-{order['id']}",
        "url": f"{APP_URL}/dashboard/orders" if APP_URL else "/dashboard/orders",
    }


def build_order_rejected_payload(order: dict, lang: Optional[str] = None) -> dict:
    short_id = _order_short(order)
    note = (order.get("admin_note") or "")[:80]
    body = note or _t("order_rejected", lang, "push_body_default")
    return {
        "title": _t("order_rejected", lang, "push_title", short_id=short_id),
        "body": body,
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"order-{order['id']}",
        "url": f"{APP_URL}/dashboard/orders" if APP_URL else "/dashboard/orders",
    }


def build_order_completed_payload(order: dict, lang: Optional[str] = None) -> dict:
    """iter55 — Sent when the admin/staff marks an order as `completed` (payout
    delivered). For `accumulate`, the tone is different (balance credited)."""
    short_id = _order_short(order)
    method = order.get("delivery_method")
    amount_to = order.get("amount_to", 0)
    to_code = order.get("to_code", "")
    field = {
        "accumulate": "push_accumulate",
        "crypto": "push_crypto",
        "cash": "push_cash",
    }.get(method, "push_transfer")
    body = _t("order_completed", lang, field, amt=amount_to, code=to_code)
    return {
        "title": _t("order_completed", lang, "push_title", short_id=short_id),
        "body": body,
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"order-{order['id']}-completed",
        "url": f"{APP_URL}/dashboard/orders" if APP_URL else "/dashboard/orders",
    }


def build_rate_changed_payload(from_code: str, to_code: str,
                                rate_normal: float, rate_vip: float,
                                for_role: str = "normal",
                                lang: Optional[str] = None) -> dict:
    """iter55 — Fanout to all clients when an exchange rate is updated.
    `for_role='vip'` shows the VIP rate; 'normal' shows the standard rate."""
    rate = rate_vip if for_role == "vip" else rate_normal
    vip_suffix = get_field("rate_change", lang, "push_vip_suffix") if for_role == "vip" else ""
    return {
        "title": _t("rate_change", lang, "title", from_code=from_code, to_code=to_code),
        "body": _t(
            "rate_change", lang, "push_body",
            from_code=from_code, to_code=to_code, rate=rate, vip_suffix=vip_suffix,
        ),
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        # Same tag per pair → replaces older rate notifications on the device.
        "tag": f"rate-{from_code}-{to_code}",
        "url": f"{APP_URL}/dashboard" if APP_URL else "/dashboard",
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


def build_new_pending_user_payload(target_user: dict, lang: Optional[str] = None) -> dict:
    name = target_user.get("name") or target_user.get("email") or "Usuario"
    phone = target_user.get("phone") or "-"
    return {
        "title": _t("new_user_pending", lang, "title"),
        "body": _t("new_user_pending", lang, "push_body", name=name, phone=phone),
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"pending-{target_user.get('user_id', 'x')}",
        "url": f"{APP_URL}/admin/users" if APP_URL else "/admin/users",
    }


def build_phone_verified_payload(target_user: dict, lang: Optional[str] = None) -> dict:
    return {
        "title": _t("phone_verified", lang, "push_title"),
        "body": _t("phone_verified", lang, "push_body"),
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"verified-{target_user.get('user_id', 'x')}",
        "url": f"{APP_URL}/dashboard" if APP_URL else "/dashboard",
    }


def build_phone_rejected_payload(target_user: dict, reason: str,
                                    lang: Optional[str] = None) -> dict:
    body = (reason or _t("phone_rejected", lang, "push_body_fallback"))[:140]
    return {
        "title": _t("phone_rejected", lang, "title"),
        "body": body,
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"rejected-{target_user.get('user_id', 'x')}",
        "url": f"{APP_URL}/dashboard" if APP_URL else "/dashboard",
    }
