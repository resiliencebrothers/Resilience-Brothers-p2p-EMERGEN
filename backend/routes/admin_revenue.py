"""Admin router — revenue dashboard, timeseries + monthly exports.

Extracted from routes/admin.py during the iter39 split. Owns:
- GET  /admin/revenue                          (P2P + marketplace aggregation)
- GET  /admin/revenue/timeseries               (per day/month buckets)
- GET  /admin/revenue/monthly/export           (CSV or PDF)
- POST /admin/revenue/monthly/send-now         (manual email trigger)

`build_revenue_timeseries` is re-exported because `scheduler.py` invokes it
through the wrapper in `server.py`.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Dict

from fastapi import APIRouter, HTTPException, Request, Response

from db_client import db
from auth_utils import require_admin, now_utc, _enforce_totp_step_up
import email_service
from revenue_report import (
    build_buckets, revenue_monthly_csv, revenue_monthly_pdf,
    revenue_analytics_csv, revenue_analytics_pdf,
)
from services.balances import build_rate_lookup, convert_to_usdt
from services.orders_helpers import compute_order_profit


router = APIRouter(tags=["Admin"])


async def _compute_courier_revenue(days: Optional[int] = None) -> dict:
    """iter208 — Company revenue from confirmed courier deliveries.

    Aggregates `platform_share_usdt` (the 20% company cut, by default) plus
    what was paid out to couriers (`courier_share_usdt`) and the total
    charged (`fee_usdt`). Only `confirmed` deliveries count — those are the
    ones where staff sealed the delivery AND the courier's USDT balance was
    credited (see routes/deliveries.py::admin_confirm_delivery).
    """
    q: Dict[str, Any] = {"status": "confirmed"}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["updated_at"] = {"$gte": cutoff}
    rows = await db.deliveries.find(
        q, {"_id": 0, "platform_share_usdt": 1,
            "courier_share_usdt": 1, "fee_usdt": 1},
    ).to_list(20000)
    platform = sum(float(r.get("platform_share_usdt") or 0) for r in rows)
    courier = sum(float(r.get("courier_share_usdt") or 0) for r in rows)
    total = sum(float(r.get("fee_usdt") or 0) for r in rows)
    return {
        "platform_usdt": round(platform, 4),
        "courier_usdt": round(courier, 4),
        "total_fees_usdt": round(total, 4),
        "count": len(rows),
    }


async def _compute_conversion_fees(days: Optional[int]) -> dict:
    """Sum the 0.01 USDT service fees charged on `POST /vip/convert` when
    a user converts fiat balance → USDT. Source of truth is the `audit_log`
    collection (see routes/orders.py::vip_convert, iter55.27).

    Returns `{total_usdt, count}`. Both fields are always numeric so the
    frontend can render safely even when no fees are recorded.
    """
    q: Dict[str, Any] = {
        "action": "vip.convert",
        "details.usdt_fee": {"$gt": 0},
    }
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["created_at"] = {"$gte": cutoff}
    rows = await db.audit_log.find(
        q, {"_id": 0, "details.usdt_fee": 1, "details.amount_from_usdt": 1}
    ).to_list(20000)
    total = 0.0
    volume = 0.0
    for r in rows:
        det = r.get("details", {}) or {}
        try:
            total += float(det.get("usdt_fee") or 0.0)
            volume += float(det.get("amount_from_usdt") or 0.0)
        except (TypeError, ValueError):
            continue
    return {"total_usdt": round(total, 4), "count": len(rows),
            "volume_usdt": round(volume, 4)}


async def _compute_vip_batch_profit(days: Optional[int]) -> dict:
    """iter113 — platform margin on approved VIP batch items (pair-based):
    each approved item stores `margin_usdt` = (amount × real_rate −
    amount × rate_vip) converted to USDT at approval time. Window filter
    uses `reviewed_at` (the moment the margin was realized).

    iter122 — also returns `volume_usdt` (sum of item `amount` converted
    from `from_code` to USDT via the FX lookup) so the Revenue module can
    reflect VIP-batch orders in the "Clientes VIP" card.
    """
    q: Dict[str, Any] = {
        "status": "approved",
        "margin_usdt": {"$nin": [None, 0]},
    }
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["reviewed_at"] = {"$gte": cutoff}
    rows = await db.vip_batch_items.find(
        q, {"_id": 0, "margin_usdt": 1, "amount": 1, "from_code": 1}
    ).to_list(20000)
    total = sum(float(r.get("margin_usdt") or 0.0) for r in rows)
    fx = await build_rate_lookup()
    volume_usdt = 0.0
    for r in rows:
        vol = convert_to_usdt(r.get("amount", 0) or 0, r.get("from_code") or "", fx)
        if vol:
            volume_usdt += vol
    return {
        "total_usdt": round(total, 4),
        "count": len(rows),
        "volume_usdt": round(volume_usdt, 4),
    }


async def _fetch_vip_batch_margins(
    year: Optional[int], month: Optional[int], days: Optional[int]
) -> list:
    """iter113 — approved batch items with margin, scoped to the window
    (year/month or last N days) by reviewed_at, for the timeseries buckets."""
    q: Dict[str, Any] = {
        "status": "approved",
        "margin_usdt": {"$nin": [None, 0]},
    }
    if year and month:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc)
               if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc))
        q["reviewed_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
    elif days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["reviewed_at"] = {"$gte": cutoff}
    return await db.vip_batch_items.find(
        q, {"_id": 0, "reviewed_at": 1, "margin_usdt": 1}
    ).to_list(20000)


async def _compute_marketplace_revenue(days: Optional[int]) -> dict:
    """Profit from delivered redemptions: total_usd - cost_usd. USD ≈ USDT for simplicity."""
    q: Dict[str, Any] = {"status": "delivered"}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["created_at"] = {"$gte": cutoff}
    rows = await db.redemptions.find(q, {"_id": 0}).to_list(20000)
    total_revenue = 0.0
    total_cost = 0.0
    by_product: dict = {}
    for r in rows:
        rev = float(r.get("total_usd") or 0.0)
        cost = float(r.get("cost_usd") or 0.0)
        total_revenue += rev
        total_cost += cost
        key = r.get("product_name", "—")
        if key not in by_product:
            by_product[key] = {
                "product": key, "units": 0, "revenue_usd": 0.0,
                "cost_usd": 0.0, "profit_usd": 0.0, "redemptions": 0,
            }
        bp = by_product[key]
        bp["units"] += int(r.get("quantity") or 0)
        bp["revenue_usd"] += rev
        bp["cost_usd"] += cost
        bp["profit_usd"] += (rev - cost)
        bp["redemptions"] += 1
    items = []
    for v in by_product.values():
        v["revenue_usd"] = round(v["revenue_usd"], 2)
        v["cost_usd"] = round(v["cost_usd"], 2)
        v["profit_usd"] = round(v["profit_usd"], 2)
        v["margin_pct"] = round((v["profit_usd"] / v["revenue_usd"] * 100), 2) if v["revenue_usd"] > 0 else 0.0
        items.append(v)
    items.sort(key=lambda x: -x["profit_usd"])
    return {
        "total_revenue_usd": round(total_revenue, 2),
        "total_cost_usd": round(total_cost, 2),
        "total_profit_usd": round(total_revenue - total_cost, 2),
        "items": items,
        "deliveries": len(rows),
    }


def _new_pair_bucket(o: dict, rate_doc: Optional[dict]) -> dict:
    rd = rate_doc or {}
    return {
        "pair": f"{o['from_code']}→{o['to_code']}",
        "from_code": o["from_code"],
        "to_code": o["to_code"],
        "orders": 0,
        "volume_from": 0.0,
        "volume_to": 0.0,
        "profit_to": 0.0,
        "profit_usdt": 0.0,
        "real_rate": rd.get("real_rate"),
        "rate_normal": rd.get("rate_normal"),
        "rate_vip": rd.get("rate_vip"),
        "avg_profit_pct": 0.0,
    }


def _role_bucket_for(order: dict) -> str:
    return "vip" if order.get("user_role") in ("vip", "admin") else "normal"


async def _accumulate_revenue_order(
    o: dict, rate_doc: Optional[dict], fx: dict,
    by_pair: dict, by_role: dict, missing: set,
) -> tuple[float, float | None]:
    """Mutate by_pair/by_role with this order. Returns (volume_usdt, profit_usdt|None)."""
    profit = await compute_order_profit(o, rate_doc)
    volume_usdt = convert_to_usdt(o["amount_from"], o["from_code"], fx) or 0.0
    role = _role_bucket_for(o)
    by_role[role]["orders"] += 1
    by_role[role]["volume_usdt"] += volume_usdt

    if profit is None:
        missing.add(f"{o['from_code']}→{o['to_code']}")
        return volume_usdt, None

    profit_usdt = convert_to_usdt(profit["amount"], profit["currency"], fx) or 0.0
    by_role[role]["profit_usdt"] += profit_usdt

    key = f"{o['from_code']}→{o['to_code']}"
    bucket = by_pair.setdefault(key, _new_pair_bucket(o, rate_doc))
    bucket["orders"] += 1
    bucket["volume_from"] += o["amount_from"]
    bucket["volume_to"] += o["amount_to"]
    bucket["profit_to"] += profit["amount"]
    bucket["profit_usdt"] += profit_usdt
    return volume_usdt, profit_usdt


def _finalize_pair_items(by_pair: dict) -> list:
    items = []
    for b in by_pair.values():
        if b["volume_to"] > 0 and b["real_rate"]:
            real_value = b["volume_from"] * float(b["real_rate"])
            b["avg_profit_pct"] = (
                round((real_value - b["volume_to"]) / real_value * 100, 3)
                if real_value > 0 else 0.0
            )
        b["profit_to"] = round(b["profit_to"], 4)
        b["profit_usdt"] = round(b["profit_usdt"], 4)
        items.append(b)
    items.sort(key=lambda x: -x["profit_usdt"])
    return items


async def _accumulate_batch_items_by_pair(
    days: Optional[int], rate_by_pair: dict, fx: dict, by_pair: dict,
) -> int:
    """iter208 — Los lotes VIP también generan ganancia por par. Aporta cada
    `vip_batch_items` aprobado al bucket del par correspondiente para que la
    tabla "Ganancia P2P por par" refleje TODO el volumen operado, no solo
    la colección `orders`. Retorna cuántos items se procesaron."""
    q: Dict[str, Any] = {
        "status": "approved",
        "to_code": {"$nin": [None, ""]},
    }
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["reviewed_at"] = {"$gte": cutoff}
    rows = await db.vip_batch_items.find(
        q, {"_id": 0, "from_code": 1, "to_code": 1, "amount": 1,
            "amount_to": 1, "margin_usdt": 1},
    ).to_list(20000)
    count = 0
    for r in rows:
        fc = r.get("from_code")
        tc = r.get("to_code")
        if not fc or not tc:
            continue
        rate_doc = rate_by_pair.get((fc, tc))
        key = f"{fc}→{tc}"
        # Reuse the same bucket shape as orders (fake object with codes).
        bucket = by_pair.setdefault(
            key, _new_pair_bucket({"from_code": fc, "to_code": tc}, rate_doc),
        )
        bucket["orders"] += 1
        bucket["volume_from"] += float(r.get("amount") or 0.0)
        bucket["volume_to"] += float(r.get("amount_to") or 0.0)
        margin_usdt = float(r.get("margin_usdt") or 0.0)
        bucket["profit_usdt"] += margin_usdt
        # profit_to expressed in the destination currency for consistency
        # with the orders side. For USDT-quoted pairs it's identical; for
        # other quotes we convert USDT → to_code via the FX lookup.
        if tc == "USDT":
            bucket["profit_to"] += margin_usdt
        else:
            rate_to_usdt = fx.get(tc)
            if rate_to_usdt and rate_to_usdt > 0:
                bucket["profit_to"] += margin_usdt / rate_to_usdt
        count += 1
    return count


async def _p2p_revenue_totals(
    orders: list, rate_by_pair: dict, fx: dict,
) -> tuple[dict, dict, set, float, float]:
    """Acumula ganancia/volumen P2P por par y por rol (extraído del endpoint)."""
    by_pair: dict = {}
    by_role: dict = {"normal": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0},
                     "vip": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0}}
    missing_rate_pairs: set = set()
    total_profit_usdt = 0.0
    total_volume_usdt = 0.0
    for o in orders:
        # Defensive: skip orders missing required fields (data hygiene guard).
        fc, tc = o.get("from_code"), o.get("to_code")
        if not fc or not tc:
            continue
        rate_doc = rate_by_pair.get((fc, tc))
        vol, prof = await _accumulate_revenue_order(
            o, rate_doc, fx, by_pair, by_role, missing_rate_pairs,
        )
        total_volume_usdt += vol
        if prof is not None:
            total_profit_usdt += prof
    return by_pair, by_role, missing_rate_pairs, total_profit_usdt, total_volume_usdt


def _merge_vip_batches_into_roles(by_role: dict, vip_batches: dict) -> None:
    """iter122 — VIPs operate through batches (`vip_batch_items`), not the
    `orders` collection. Fold approved batch metrics into the "Clientes VIP"
    role bucket so the Revenue module reflects real VIP activity instead of
    zeroed cards. Also expose a `batches` breakdown for the UI."""
    by_role["vip"]["orders"] += vip_batches["count"]
    by_role["vip"]["volume_usdt"] += vip_batches.get("volume_usdt", 0.0)
    by_role["vip"]["profit_usdt"] += vip_batches["total_usdt"]
    by_role["vip"]["batches"] = {
        "orders": vip_batches["count"],
        "volume_usdt": vip_batches.get("volume_usdt", 0.0),
        "profit_usdt": vip_batches["total_usdt"],
    }
    for r in by_role.values():
        r["profit_usdt"] = round(r["profit_usdt"], 4)
        r["volume_usdt"] = round(r["volume_usdt"], 4)


@router.get("/admin/revenue")
async def admin_revenue(request: Request, days: Optional[int] = None) -> Any:
    await require_admin(request)
    q = {"status": {"$in": ["approved", "completed"]}}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["updated_at"] = {"$gte": cutoff}

    orders = await db.orders.find(q, {"_id": 0}).to_list(20000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await build_rate_lookup()

    (by_pair, by_role, missing_rate_pairs,
     total_profit_usdt, total_volume_usdt) = await _p2p_revenue_totals(
        orders, rate_by_pair, fx)

    # iter208 — Add approved VIP batch items to by_pair so pairs traded
    # exclusively via lotes VIP (e.g. ZELLE→CUPT, ZELLE→CUP) appear in
    # the "Ganancia P2P por par" table with their real volume + profit.
    batch_items_count = await _accumulate_batch_items_by_pair(
        days, rate_by_pair, fx, by_pair,
    )

    pair_items = _finalize_pair_items(by_pair)

    marketplace = await _compute_marketplace_revenue(days)
    conversion_fees = await _compute_conversion_fees(days)
    vip_batches = await _compute_vip_batch_profit(days)
    courier = await _compute_courier_revenue(days)

    _merge_vip_batches_into_roles(by_role, vip_batches)

    grand_total_profit = (
        total_profit_usdt
        + marketplace["total_profit_usd"]
        + conversion_fees["total_usdt"]
        + vip_batches["total_usdt"]
        + courier["platform_usdt"]
    )
    total_volume_all = (
        total_volume_usdt
        + vip_batches.get("volume_usdt", 0.0)
        + marketplace["total_revenue_usd"]
        + conversion_fees.get("volume_usdt", 0.0)
        + courier["total_fees_usdt"]
    )

    return {
        "total_profit_usdt": round(grand_total_profit, 4),
        "p2p_profit_usdt": round(total_profit_usdt, 4),
        "marketplace_profit_usdt": round(marketplace["total_profit_usd"], 4),
        "conversion_fees_usdt": conversion_fees["total_usdt"],
        "conversion_fees_count": conversion_fees["count"],
        "vip_batches_profit_usdt": vip_batches["total_usdt"],
        "vip_batches_count": vip_batches["count"],
        # iter208 — Company revenue from confirmed courier deliveries.
        # `courier_platform_usdt` is the empresa's share, `courier_couriers_usdt`
        # is what was paid out to couriers (already credited to their balances).
        "courier_platform_usdt": courier["platform_usdt"],
        "courier_couriers_usdt": courier["courier_usdt"],
        "courier_total_fees_usdt": courier["total_fees_usdt"],
        "courier_deliveries_count": courier["count"],
        "total_volume_usdt": round(total_volume_usdt, 4),
        "profit_margin_pct": round((total_profit_usdt / total_volume_usdt * 100), 3) if total_volume_usdt > 0 else 0.0,
        # iter157 — TOTAL company profitability: every profit source (P2P +
        # marketplace + VIP batches + conversion fees) over the total volume
        # moved in the same window (P2P volume + VIP batch volume +
        # marketplace revenue + converted volume). Respects the `days` filter.
        "total_margin_pct": round((grand_total_profit / total_volume_all * 100), 3) if total_volume_all > 0 else 0.0,
        "total_volume_all_usdt": round(total_volume_all, 4),
        "by_pair": pair_items,
        "by_role": by_role,
        "marketplace": marketplace,
        "missing_real_rate_pairs": sorted(missing_rate_pairs),
        "orders_total": len(orders) + batch_items_count,
        "orders_p2p_count": len(orders),
        "batch_items_count": batch_items_count,
    }


async def _fetch_conversion_fees(
    year: Optional[int], month: Optional[int], days: Optional[int]
) -> list:
    """iter55.28 — pull `vip.convert` audit rows with a positive `usdt_fee`
    scoped to the same window as the caller (year/month or last N days)."""
    q: Dict[str, Any] = {
        "action": "vip.convert",
        "details.usdt_fee": {"$gt": 0},
    }
    if year and month:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc)
               if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc))
        q["created_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
    elif days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["created_at"] = {"$gte": cutoff}
    return await db.audit_log.find(
        q, {"_id": 0, "created_at": 1, "details.usdt_fee": 1}
    ).to_list(20000)


async def build_revenue_timeseries(granularity: str, days: Optional[int] = None,
                                    year: Optional[int] = None, month: Optional[int] = None) -> Any:
    """Build per-day or per-month buckets for the admin revenue dashboard.

    Filters:
      - `days`: restrict to last N days (preferred for daily charts).
      - `year`/`month`: restrict to a specific calendar month (used for the monthly export).
    """
    order_q: dict = {"status": {"$in": ["approved", "completed"]}}
    redemption_q: dict = {"status": "delivered"}

    if year and month:
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc)
               if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc))
        order_q["updated_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
        redemption_q["created_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
    elif days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        order_q["updated_at"] = {"$gte": cutoff}
        redemption_q["created_at"] = {"$gte": cutoff}

    orders = await db.orders.find(order_q, {"_id": 0}).to_list(20000)
    redemptions = await db.redemptions.find(redemption_q, {"_id": 0}).to_list(20000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await build_rate_lookup()

    profit_map: dict = {}
    for o in orders:
        o["_volume_usdt"] = convert_to_usdt(o["amount_from"], o["from_code"], fx) or 0.0
        rate_doc = rate_by_pair.get((o["from_code"], o["to_code"]))
        prof = await compute_order_profit(o, rate_doc)
        if prof is None:
            continue
        prof_usdt = convert_to_usdt(prof["amount"], prof["currency"], fx) or 0.0
        profit_map[o["id"]] = prof_usdt

    conversion_fees = await _fetch_conversion_fees(year, month, days)
    vip_batch_margins = await _fetch_vip_batch_margins(year, month, days)

    return build_buckets(orders, redemptions, profit_map, granularity,
                          conversion_fees=conversion_fees,
                          vip_batch_margins=vip_batch_margins)


@router.get("/admin/revenue/timeseries")
async def admin_revenue_timeseries(request: Request, granularity: str = "day",
                                     days: Optional[int] = None) -> Any:
    await require_admin(request)
    if granularity not in ("day", "month"):
        raise HTTPException(status_code=400, detail="granularity inválida (day|month)")
    rows = await build_revenue_timeseries(granularity, days=days)
    return {"granularity": granularity, "rows": rows}


@router.get("/admin/revenue/day-detail")
async def admin_revenue_day_detail(request: Request, date: str) -> Any:
    """Breakdown of one daily bucket: the exact P2P orders, marketplace
    deliveries, VIP batch items and USDT conversion fees behind the total."""
    await require_admin(request)
    try:
        d0 = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="fecha inválida (YYYY-MM-DD)")
    win = {"$gte": date, "$lt": (d0 + timedelta(days=1)).strftime("%Y-%m-%d")}

    orders = await db.orders.find(
        {"status": {"$in": ["approved", "completed"]}, "updated_at": win}, {"_id": 0},
    ).to_list(2000)
    redemptions = await db.redemptions.find(
        {"status": "delivered", "created_at": win}, {"_id": 0},
    ).to_list(2000)
    batch_items = await db.vip_batch_items.find(
        {"status": "approved", "margin_usdt": {"$nin": [None, 0]}, "reviewed_at": win},
        {"_id": 0},
    ).sort("reviewed_at", 1).to_list(5000)
    fee_rows = await db.audit_log.find(
        {"action": "vip.convert", "details.usdt_fee": {"$gt": 0}, "created_at": win},
        {"_id": 0, "created_at": 1, "actor_email": 1, "actor_name": 1, "details": 1},
    ).sort("created_at", 1).to_list(5000)

    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await build_rate_lookup()

    order_rows, p2p_total, volume_total = [], 0.0, 0.0
    for o in sorted(orders, key=lambda x: x.get("updated_at") or ""):
        vol = convert_to_usdt(o["amount_from"], o["from_code"], fx) or 0.0
        prof = await compute_order_profit(o, rate_by_pair.get((o["from_code"], o["to_code"])))
        prof_usdt = (convert_to_usdt(prof["amount"], prof["currency"], fx) or 0.0) if prof else 0.0
        p2p_total += prof_usdt
        volume_total += vol
        order_rows.append({
            "id": o["id"],
            "pair": f"{o['from_code']}→{o['to_code']}",
            "user_name": o.get("user_name") or o.get("user_email") or "—",
            "user_role": o.get("user_role") or "",
            "amount_from": o.get("amount_from"), "from_code": o.get("from_code"),
            "amount_to": o.get("amount_to"), "to_code": o.get("to_code"),
            "profit_usdt": round(prof_usdt, 4),
        })

    mkt_rows, mkt_total = [], 0.0
    for r in redemptions:
        prof_amt = float(r.get("total_usd") or 0.0) - float(r.get("cost_usd") or 0.0)
        mkt_total += prof_amt
        mkt_rows.append({
            "id": r["id"], "product_name": r.get("product_name") or "—",
            "user_name": r.get("user_name") or r.get("user_email") or "—",
            "quantity": r.get("quantity") or 1,
            "total_usd": float(r.get("total_usd") or 0.0),
            "cost_usd": float(r.get("cost_usd") or 0.0),
            "profit_usdt": round(prof_amt, 4),
        })

    vip_ids = list({it.get("vip_user_id") for it in batch_items if it.get("vip_user_id")})
    vip_names: Dict[str, str] = {}
    if vip_ids:
        async for u in db.users.find({"user_id": {"$in": vip_ids}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}):
            vip_names[u["user_id"]] = u.get("name") or u.get("email") or "—"
    vip_rows, vip_total = [], 0.0
    for it in batch_items:
        m = float(it.get("margin_usdt") or 0.0)
        vip_total += m
        vip_rows.append({
            "id": it["id"],
            "vip_name": vip_names.get(it.get("vip_user_id"), "—"),
            "holder": it.get("card_number") or it.get("holder_name") or "—",
            "pair": f"{it.get('from_code')}→{it.get('to_code')}" if it.get("to_code") else (it.get("currency") or "—"),
            "amount": it.get("amount"), "from_code": it.get("from_code") or it.get("currency"),
            "amount_to": it.get("amount_to"), "to_code": it.get("to_code"),
            "margin_usdt": round(m, 4),
        })

    fee_list, fees_total = [], 0.0
    for row in fee_rows:
        det = row.get("details") or {}
        fee = float(det.get("usdt_fee") or 0.0)
        fees_total += fee
        fee_list.append({
            "created_at": row.get("created_at"),
            "user": row.get("actor_name") or row.get("actor_email") or "—",
            "pair": f"{det.get('from_code')}→{det.get('to_code')}" if det.get("to_code") else "—",
            "amount_from": det.get("amount_from"),
            "fee_usdt": round(fee, 4),
        })

    return {
        "date": date,
        "orders": order_rows, "p2p_profit_usdt": round(p2p_total, 4),
        "volume_usdt": round(volume_total, 4),
        "marketplace": mkt_rows, "marketplace_profit_usdt": round(mkt_total, 4),
        "vip_batch_items": vip_rows, "vip_batches_profit_usdt": round(vip_total, 4),
        "conversions": fee_list, "conversion_fees_usdt": round(fees_total, 4),
        "total_profit_usdt": round(p2p_total + mkt_total + vip_total + fees_total, 4),
    }


@router.get("/admin/revenue/monthly/export")
async def admin_revenue_monthly_export(request: Request, year: int, month: int,
                                          format: str = "csv") -> Any:
    """Export the daily breakdown of a calendar month as CSV or PDF."""
    await require_admin(request)
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="mes inválido")
    if format not in ("csv", "pdf"):
        raise HTTPException(status_code=400, detail="formato inválido (csv|pdf)")

    rows = await build_revenue_timeseries("day", year=year, month=month)
    rows_asc = sorted(rows, key=lambda x: x["bucket"])
    period_label = f"{year}-{month:02d}"

    if format == "csv":
        payload = revenue_monthly_csv(rows_asc, period_label)
        headers = {"Content-Disposition": f'attachment; filename="ganancia-{period_label}.csv"'}
        return Response(content=payload, media_type="text/csv; charset=utf-8", headers=headers)

    totals = _build_totals(rows_asc)
    payload = revenue_monthly_pdf(rows_asc, period_label, totals)
    headers = {"Content-Disposition": f'attachment; filename="ganancia-{period_label}.pdf"'}
    return Response(content=payload, media_type="application/pdf", headers=headers)


def _build_totals(rows_asc: list) -> dict:
    """Aggregate the totals card for the monthly export/email — includes
    iter55.28 conversion fees + iter113 VIP batch margins."""
    return {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "conversion_fees": sum(r.get("conversion_fees_usdt", 0.0) for r in rows_asc),
        "vip_batches": sum(r.get("vip_batches_profit_usdt", 0.0) for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }


@router.get("/admin/revenue/analytics/export")
async def admin_revenue_analytics_export(
    request: Request,
    format: str = "pdf",
    days: Optional[int] = None,
) -> Any:
    """iter55.36l — Multi-month analytics export used by the "Estadísticas"
    dialog in `/admin/revenue`. Format: `csv` or `pdf`. Optional `days`
    filter restricts the summary/highlights to the same window used by
    the on-screen filter; the monthly table always covers all history so
    year-over-year comparison stays meaningful."""
    await require_admin(request)
    if format not in ("csv", "pdf"):
        raise HTTPException(status_code=400, detail="format debe ser csv o pdf")

    # Reuse the same summary that powers `/admin/revenue`, respecting `days`.
    summary = await admin_revenue(request, days=days)
    # Monthly rows always cover all time — the report is a *historical*
    # comparison, unlike the current-period summary above.
    monthly = await build_revenue_timeseries("month")
    monthly_rows = sorted(monthly, key=lambda x: x["bucket"])

    period_label = (
        f"últimos {days} días" if days and days > 0 else "todo el tiempo"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")

    if format == "csv":
        payload = revenue_analytics_csv(monthly_rows, summary, period_label)
        headers = {
            "Content-Disposition": f'attachment; filename="estadisticas-ingresos-{stamp}.csv"',
        }
        return Response(content=payload, media_type="text/csv; charset=utf-8",
                        headers=headers)

    payload = revenue_analytics_pdf(monthly_rows, summary, period_label)
    headers = {
        "Content-Disposition": f'attachment; filename="estadisticas-ingresos-{stamp}.pdf"',
    }
    return Response(content=payload, media_type="application/pdf", headers=headers)


@router.post("/admin/revenue/monthly/send-now")
async def admin_revenue_send_now(payload: dict, request: Request) -> Any:
    """Manually trigger the monthly revenue email."""
    actor = await require_admin(request)
    await _enforce_totp_step_up(actor, payload.get("totp_code"),
                                 action_label="enviar reporte mensual")
    year = int(payload.get("year") or 0)
    month = int(payload.get("month") or 0)
    if month < 1 or month > 12 or year < 2020:
        raise HTTPException(status_code=400, detail="año/mes inválido")
    rows = await build_revenue_timeseries("day", year=year, month=month)
    rows_asc = sorted(rows, key=lambda x: x["bucket"])
    totals = _build_totals(rows_asc)
    pdf_bytes = revenue_monthly_pdf(rows_asc, f"{year}-{month:02d}", totals)
    from admin_alerts import resolve_admin_email_recipients
    recipients = await resolve_admin_email_recipients(db)
    sent = 0
    for to_addr in recipients:
        if email_service.notify_monthly_revenue(
            to_addr, f"{year}-{month:02d}", totals, pdf_bytes
        ):
            sent += 1
    return {"ok": True, "sent": sent, "total_admins": len(recipients),
            "period": f"{year}-{month:02d}"}
