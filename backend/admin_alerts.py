"""Admin alert dispatcher: sends push + email to ALL admins when triggers fire."""
import os
import logging
from email_service import _base_template, _send
from push_service import send_push

logger = logging.getLogger(__name__)
APP_URL = os.environ.get("APP_PUBLIC_URL", "")


async def resolve_admin_email_recipients(db, admins: list | None = None) -> list[str]:
    """Resolve which emails should receive ops alerts.

    If `settings.global.ops_notifications_email` is set, ALL admin emails are
    funneled to that single inbox. Otherwise each admin's personal email is used.
    """
    settings_doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    ops_email = (settings_doc or {}).get("ops_notifications_email")
    if ops_email:
        return [ops_email]
    if admins is None:
        admins = await db.users.find({"role": "admin"}, {"_id": 0, "email": 1}).to_list(200)
    return [a["email"] for a in admins if a.get("email")]


async def _send_push_to_subscription(sub: dict, payload: dict) -> tuple[int, str | None]:
    """Send one push and normalise the result. Returns (delivered_count, dead_id_or_None)."""
    result = send_push(sub["subscription"], payload)
    if result == "ok":
        return 1, None
    if result == "dead":
        return 0, sub["id"]
    return 0, None


async def _push_fanout_to_admin(db, admin: dict, payload: dict) -> tuple[int, list[str]]:
    """Push `payload` to every subscription of a single admin.
    Guard-clause style keeps nesting shallow."""
    try:
        subs = await db.push_subscriptions.find(
            {"user_id": admin["user_id"]}, {"_id": 0}
        ).to_list(20)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Push subscription fetch for admin {admin.get('email')} failed: {e}")
        return 0, []

    sent = 0
    dead: list[str] = []
    for s in subs:
        delivered, dead_id = await _send_push_to_subscription(s, payload)
        sent += delivered
        if dead_id:
            dead.append(dead_id)
    return sent, dead


async def _push_fanout_to_admins(db, admins: list, payload: dict) -> tuple[int, list[str]]:
    """Send `payload` via Web Push to every device subscribed by any admin.
    Returns (pushes_sent, dead_subscription_ids)."""
    push_sent = 0
    dead_ids: list[str] = []
    for admin in admins:
        sent, dead = await _push_fanout_to_admin(db, admin, payload)
        push_sent += sent
        dead_ids.extend(dead)
    return push_sent, dead_ids


async def _email_fanout_to_admins(db, admins: list, subject: str, html: str) -> int:
    """Send `html` to the resolved ops mailbox(es). Returns emails_sent."""
    recipients = await resolve_admin_email_recipients(db, admins=admins)
    sent = 0
    for to_addr in recipients:
        try:
            if _send(to_addr, subject, html):
                sent += 1
        except Exception as e:  # noqa: BLE001
            logger.error(f"Email to {to_addr} failed: {e}")
    return sent


async def notify_all_admins(db, *, title: str, body: str, url_path: str = "/admin"):
    """Send a notification (push + email) to all users with role='admin'.
    `db` is the motor AsyncIOMotorDatabase instance.

    Email behavior: if `settings.global.ops_notifications_email` is set, a single
    email is sent to that inbox (centralized ops mailbox). Otherwise it fans out
    to each admin's personal email. Push notifications always fan out per admin.
    """
    admins = await db.users.find({"role": "admin"}, {"_id": 0}).to_list(50)
    if not admins:
        return {"admins": 0, "pushes": 0, "emails": 0}

    target_url = f"{APP_URL}{url_path}" if APP_URL else url_path
    push_payload = {
        "title": title,
        "body": body,
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "tag": f"admin-alert-{title[:20]}",
        "url": target_url,
    }
    html_body = f"""
      <p style="color:#A3A3A3;font-size:14px;line-height:1.6;margin:0 0 16px;">{body}</p>
      <a href="{target_url}" style="display:inline-block;margin-top:12px;background:#8B5CF6;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">REVISAR EN EL PANEL →</a>
    """
    html = _base_template(title, html_body)

    push_sent, dead_ids = await _push_fanout_to_admins(db, admins, push_payload)
    email_sent = await _email_fanout_to_admins(
        db, admins, f"[Resilience Admin] {title}", html
    )

    if dead_ids:
        try:
            await db.push_subscriptions.delete_many({"id": {"$in": dead_ids}})
        except Exception:
            pass

    return {"admins": len(admins), "pushes": push_sent, "emails": email_sent}


async def get_vip_threshold(db) -> float:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        return float(os.environ.get("VIP_ALERT_THRESHOLD_USDT", 5000))
    return float(doc.get("vip_threshold_usdt", 5000))
