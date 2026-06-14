"""Admin alert dispatcher: sends push + email to ALL admins when triggers fire."""
import os
import logging
import asyncio
from email_service import _base_template, _send
from push_service import send_push

logger = logging.getLogger(__name__)
APP_URL = os.environ.get("APP_PUBLIC_URL", "")


async def notify_all_admins(db, *, title: str, body: str, url_path: str = "/admin"):
    """Send a notification (push + email) to all users with role='admin'.
    `db` is the motor AsyncIOMotorDatabase instance.
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

    for admin in admins:
        # Push to all admin's devices
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
        # Email
        try:
            if admin.get("email"):
                html = _base_template(title, html_body)
                if _send(admin["email"], f"[Resilience Admin] {title}", html):
                    email_sent += 1
        except Exception as e:
            logger.error(f"Email to admin {admin.get('email')} failed: {e}")

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
