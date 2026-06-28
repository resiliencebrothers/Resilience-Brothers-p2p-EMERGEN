"""Admin alert dispatcher: sends push + email to ALL admins when triggers fire."""
import os
import logging
import asyncio
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
      <a href="{target_url}" style="display:inline-block;margin-top:12px;background:#EAB308;color:#000;font-weight:bold;text-decoration:none;padding:12px 24px;letter-spacing:0.5px;">REVISAR EN EL PANEL →</a>
    """

    push_sent = 0
    email_sent = 0
    dead_ids = []

    # Push fan-out — always per admin device
    for admin in admins:
        try:
            subs = await db.push_subscriptions.find({"user_id": admin["user_id"]}, {"_id": 0}).to_list(20)
            for s in subs:
                result = send_push(s["subscription"], push_payload)
                if result == "ok":
                    push_sent += 1
                elif result == "dead":
                    dead_ids.append(s["id"])
        except Exception as e:
            logger.error(f"Push to admin {admin.get('email')} failed: {e}")

    # Email — centralised inbox OR per-admin fan-out
    email_recipients = await resolve_admin_email_recipients(db, admins=admins)
    html = _base_template(title, html_body)
    for to_addr in email_recipients:
        try:
            if _send(to_addr, f"[Resilience Admin] {title}", html):
                email_sent += 1
        except Exception as e:
            logger.error(f"Email to {to_addr} failed: {e}")

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
