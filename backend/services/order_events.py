"""Order live-event fan-out — shared by admin routes and the
reconciliation engine (extracted from routes/admin.py to avoid
service→route imports)."""
import logging

logger = logging.getLogger("order_events")


async def publish_order_status_sse(order_id: str, updated: dict,
                                    new_status: str, prev_status: str) -> None:
    """Fan-out `order_status_changed` + `balance_updated` to owner + admins.
    Isolated in a try/except so a live-bus hiccup can't fail the HTTP write."""
    try:
        from services.live_bus import publish as live_publish
        target_uid = updated.get("user_id") if isinstance(updated, dict) else None
        status_payload = {
            "order_id": order_id,
            "status": new_status,
            "prev_status": prev_status,
            "from_code": updated.get("from_code"),
            "to_code": updated.get("to_code"),
            "amount_from": updated.get("amount_from"),
            "amount_to": updated.get("amount_to"),
        }
        if target_uid:
            await live_publish("order_status_changed", status_payload, user_id=target_uid)
            await live_publish("balance_updated", {"reason": "order", "order_id": order_id},
                               user_id=target_uid)
            await live_publish("ledger_changed",
                               {"reason": "order", "order_id": order_id,
                                "user_id": target_uid},
                               roles=("admin", "employee"))
        await live_publish("order_status_changed", status_payload,
                           roles=("admin", "employee"))
    except Exception as e:
        logger.error(f"Order SSE publish failed: {e}")
