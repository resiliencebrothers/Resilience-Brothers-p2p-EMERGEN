"""iter224 — Alerta Caja Baja: avisa a los admins (push + email + campana)
cuando una cuenta interna o la caja de efectivo baja del saldo mínimo
configurado por cuenta (`min_balance_alert` en payment_accounts /
fund_accounts). Dedup vía flag `low_balance_alerted_at`; al recuperarse por
encima del mínimo el flag se limpia y una nueva caída vuelve a avisar.
"""
import logging

from db_client import db
from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)


async def _notify_low(account_id: str, label: str, code: str,
                      bal: float, minimum: float) -> None:
    title = f"Saldo bajo: {label}"
    body = (f"La cuenta «{label}» ({code}) bajó a {bal:,.2f} {code} "
            f"(mínimo configurado: {minimum:,.2f}). Considera reponer fondos.")
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(db, title=title, body=body,
                                url_path="/admin/company-funds")
    except Exception as e:  # noqa: BLE001
        logger.error(f"low fund push/email failed: {e}")
    try:
        from routes.notifications import _insert_notification
        admins = await db.users.find({"role": "admin"},
                                     {"_id": 0, "user_id": 1}).to_list(50)
        for a in admins:
            await _insert_notification(
                recipient_user_id=a["user_id"], type="low_fund_balance",
                title=title, message=body,
                data={"account_id": account_id, "currency": code,
                      "balance": bal, "minimum": minimum})
    except Exception as e:  # noqa: BLE001
        logger.error(f"low fund in-app notify failed: {e}")


async def check_low_fund_balances() -> int:
    """Revisa todas las cuentas con mínimo configurado. Devuelve nº de alertas."""
    watched = []
    async for pa in db.payment_accounts.find(
            {"min_balance_alert": {"$gt": 0}}, {"_id": 0}):
        watched.append(("payment_accounts", pa, pa.get("currency_code")))
    async for fa in db.fund_accounts.find(
            {"min_balance_alert": {"$gt": 0}}, {"_id": 0}):
        watched.append(("fund_accounts", fa, fa.get("currency")))
    if not watched:
        return 0
    from services.fund_accounts import account_assigned_balances
    balances_by_code: dict = {}
    alerts = 0
    for coll, acc, raw_code in watched:
        code = (raw_code or "").upper()
        if not code:
            continue
        if code not in balances_by_code:
            balances_by_code[code] = await account_assigned_balances(code)
        bal = round(float(balances_by_code[code].get(acc["id"], 0.0)), 2)
        minimum = float(acc.get("min_balance_alert") or 0)
        collection = db[coll]
        if bal < minimum:
            if acc.get("low_balance_alerted_at"):
                continue
            await collection.update_one(
                {"id": acc["id"]},
                {"$set": {"low_balance_alerted_at": iso(now_utc())}})
            label = acc.get("label") or acc.get("name") or acc["id"]
            await _notify_low(acc["id"], label, code, bal, minimum)
            alerts += 1
        elif acc.get("low_balance_alerted_at"):
            await collection.update_one(
                {"id": acc["id"]},
                {"$unset": {"low_balance_alerted_at": ""}})
    return alerts
