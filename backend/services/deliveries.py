"""iter199 — courier deliveries (Fase 2).

One `deliveries` document per physical delivery job (cash withdrawal or
marketplace redemption). Created automatically when a courier fee is charged
and manually (admin) for FREE deliveries (≥ free threshold).

Earnings split: courier gets `courier_share_pct` (default 80%) of the fee,
platform keeps the rest. The courier share is credited to the courier's
in-platform USDT balance when STAFF confirms the delivered job.
"""
import logging
import uuid
from typing import Any, Optional

from db_client import db
from auth_utils import iso, now_utc

logger = logging.getLogger("deliveries")

ACTIVE_STATUSES = ("available", "accepted", "on_the_way", "arrived", "delivered")


async def get_share_pct() -> float:
    doc = await db.settings.find_one({"id": "global"},
                                     {"_id": 0, "courier_share_pct": 1}) or {}
    raw = doc.get("courier_share_pct")
    return float(raw) if raw is not None else 80.0


def compute_shares(fee_usdt: float, share_pct: float) -> tuple:
    courier = round(float(fee_usdt) * share_pct / 100.0, 2)
    platform = round(float(fee_usdt) - courier, 2)
    return courier, platform


def _ref_display(kind: str, ref: dict) -> dict:
    if kind == "withdrawal":
        # `details` is a formatted string on modern cash withdrawals but a
        # dict on some older/imported docs — support both (iter199 bugfix).
        raw = ref.get("details")
        if isinstance(raw, dict):
            parts = [raw.get("receiver_name"), raw.get("address"),
                     raw.get("phone")]
            address = " — ".join(str(p) for p in parts if p)
        else:
            address = str(raw or "")
        return {
            "user_id": ref.get("user_id"),
            "client_name": ref.get("user_name") or "",
            "address": address,
            "province": ref.get("province"),
            "amount_label": f"{ref.get('amount_usd', 0)} {ref.get('currency', '')}",
        }
    if kind == "deposit":
        # iter208 — cash-courier deposit: the courier goes to the client's
        # address to PICK UP the cash. Compose the same address block used
        # for withdrawals so the courier gets everything in one glance.
        parts = [ref.get("contact_name"), ref.get("pickup_address"),
                 ref.get("pickup_phone")]
        address = " — ".join(str(p) for p in parts if p)
        return {
            "user_id": ref.get("user_id"),
            "client_name": ref.get("user_name") or "",
            "address": address,
            "province": None,
            "amount_label": (
                f"Recoger {ref.get('amount', 0)} {ref.get('currency', '')}"
            ),
        }
    return {
        "user_id": ref.get("user_id"),
        "client_name": ref.get("user_name") or "",
        "address": ref.get("delivery_address") or "",
        "province": None,
        "amount_label": f"{ref.get('product_name', '')} ×{ref.get('quantity', 1)}",
    }


async def build_delivery_doc(kind: str, ref: dict, *, km: float, fee_usdt: float,
                             created_by: Optional[str] = None) -> dict:
    share_pct = await get_share_pct()
    courier_share, platform_share = compute_shares(fee_usdt, share_pct)
    disp = _ref_display(kind, ref)
    now = iso(now_utc())
    return {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "ref_id": ref["id"],
        "user_id": disp["user_id"],
        "client_name": disp["client_name"],
        "address": disp["address"],
        "province": disp["province"],
        "amount_label": disp["amount_label"],
        "delivery_latitude": ref.get("delivery_latitude"),
        "delivery_longitude": ref.get("delivery_longitude"),
        "km": float(km or 0),
        "fee_usdt": float(fee_usdt or 0),
        "share_pct_snapshot": share_pct,
        "courier_share_usdt": courier_share,
        "platform_share_usdt": platform_share,
        "status": "available",
        "courier_id": None,
        "courier_name": None,
        "payout_credited": False,
        "payout_credited_at": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
        "timeline": [{"status": "available", "at": now, "by": created_by}],
    }


async def _broadcast_new_delivery_to_couriers(doc: dict) -> None:
    """iter208 — Cuando aparece una NUEVA entrega disponible, hace push a
    todos los mensajeros activos para que vean al toque el trabajo y puedan
    aceptarlo antes que otro. Best-effort, nunca rompe el flujo principal."""
    try:
        from push_service import (
            send_push_to_user, build_generic_admin_alert_payload,
        )
        share = float(doc.get("courier_share_usdt") or 0)
        is_pickup = doc.get("kind") == "deposit"
        title = ("🛵 Nueva recogida disponible" if is_pickup
                 else "🛵 Nueva entrega disponible")
        share_line = (f" · Ganas {share} USDT" if share > 0 else "")
        body = (f"{doc.get('client_name', '')} · {doc.get('amount_label', '')}"
                f"{share_line}")
        payload = build_generic_admin_alert_payload(
            title=title, body=body,
            url="/dashboard/deliveries",
            tag=f"delivery-new-{doc['id']}",
        )
        couriers = await db.users.find(
            {"is_courier": True},
            {"_id": 0, "user_id": 1},
        ).to_list(500)
        for c in couriers:
            try:
                await send_push_to_user(db, c["user_id"], payload)
            except Exception:
                pass
    except Exception as e:
        # Nunca dejamos que un error de push impida crear la entrega.
        import logging
        logging.error(f"broadcast new delivery push failed: {e}")


async def ensure_delivery_job(kind: str, ref: dict, *, km: float,
                              fee_usdt: float,
                              actor_id: Optional[str] = None) -> Any:
    """iter205 — crea el trabajo si no existe (permite fee 0: las entregas
    GRATIS ≥ umbral siguen requiriendo mensajero). No toca trabajos activos."""
    active = await db.deliveries.find_one(
        {"kind": kind, "ref_id": ref["id"], "status": {"$ne": "cancelled"}},
        {"_id": 0},
    )
    if active:
        return active
    doc = await build_delivery_doc(kind, ref, km=km, fee_usdt=fee_usdt,
                                   created_by=actor_id)
    await db.deliveries.insert_one(dict(doc))
    # iter208 — broadcast a mensajeros disponibles.
    await _broadcast_new_delivery_to_couriers(doc)
    return doc


async def cancel_active_delivery(kind: str, ref_id: str,
                                 actor_id: Optional[str] = None,
                                 note: str = "") -> None:
    """iter205 — cancela el trabajo activo (no confirmado) cuando la
    operación origen muere (retiro/canje rechazado o cancelado)."""
    now = iso(now_utc())
    await db.deliveries.update_one(
        {"kind": kind, "ref_id": ref_id,
         "status": {"$nin": ["cancelled", "confirmed"]}},
        {"$set": {"status": "cancelled", "updated_at": now},
         "$push": {"timeline": {"status": "cancelled", "at": now,
                                "by": actor_id, "note": note}}},
    )


async def upsert_delivery_for_charge(kind: str, ref: dict, *, km: float,
                                     fee_usdt: float,
                                     actor_id: Optional[str] = None) -> Any:
    """Keep the delivery job in sync with its courier-fee charge.
    fee > 0 → create/update the active job. fee == 0 (annulled) → cancel it.
    A confirmed job is history and is never rewritten."""
    active = await db.deliveries.find_one(
        {"kind": kind, "ref_id": ref["id"], "status": {"$ne": "cancelled"}},
        {"_id": 0},
    )
    now = iso(now_utc())
    if fee_usdt <= 0:
        if active and active["status"] != "confirmed":
            await db.deliveries.update_one({"id": active["id"]}, {
                "$set": {"status": "cancelled", "updated_at": now},
                "$push": {"timeline": {"status": "cancelled", "at": now,
                                       "by": actor_id, "note": "cobro anulado"}},
            })
        return None
    if active:
        if active["status"] == "confirmed":
            return active
        share_pct = await get_share_pct()
        courier_share, platform_share = compute_shares(fee_usdt, share_pct)
        await db.deliveries.update_one({"id": active["id"]}, {"$set": {
            "km": float(km or 0), "fee_usdt": float(fee_usdt),
            "share_pct_snapshot": share_pct,
            "courier_share_usdt": courier_share,
            "platform_share_usdt": platform_share,
            "updated_at": now,
        }})
        return await db.deliveries.find_one({"id": active["id"]}, {"_id": 0})
    doc = await build_delivery_doc(kind, ref, km=km, fee_usdt=fee_usdt,
                                   created_by=actor_id)
    await db.deliveries.insert_one(dict(doc))
    # iter208 — broadcast a mensajeros cuando aparece una nueva disponible.
    await _broadcast_new_delivery_to_couriers(doc)
    return doc
