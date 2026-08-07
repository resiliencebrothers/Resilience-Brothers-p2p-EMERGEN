"""iter159 — One-call helper to broadcast balance mutations live.

`balance_updated` goes to the affected user's own tabs (their dashboards
re-fetch balances instantly); `ledger_changed` fans out to admin/staff so
revenue stats, company funds and tables refresh without F5.
"""
import logging

logger = logging.getLogger(__name__)


async def emit_balance_changed(user_id: str, reason: str, **extra) -> None:
    try:
        from services.live_bus import publish
        payload = {"reason": reason, "user_id": user_id, **extra}
        await publish("balance_updated", payload, user_id=user_id)
        await publish("ledger_changed", payload, roles=("admin", "employee"))
    except Exception as e:  # noqa: BLE001
        logger.error(f"emit_balance_changed({reason}) failed: {e}")
