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
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response

from db_client import db
from auth_utils import require_admin, now_utc, _enforce_totp_step_up
import email_service
from revenue_report import build_buckets, revenue_monthly_csv, revenue_monthly_pdf
from services.balances import build_rate_lookup, convert_to_usdt
from services.orders_helpers import compute_order_profit


router = APIRouter(tags=["Admin"])


async def _compute_marketplace_revenue(days: Optional[int]) -> dict:
    """Profit from delivered redemptions: total_usd - cost_usd. USD ≈ USDT for simplicity."""
    q = {"status": "delivered"}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["created_at"] = {"$gte": cutoff}
    rows = await db.redemptions.find(q, {"_id": 0}).to_list(5000)
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


def _new_pair_bucket(o: dict, rate_doc: dict) -> dict:
    return {
        "pair": f"{o['from_code']}→{o['to_code']}",
        "from_code": o["from_code"],
        "to_code": o["to_code"],
        "orders": 0,
        "volume_from": 0.0,
        "volume_to": 0.0,
        "profit_to": 0.0,
        "profit_usdt": 0.0,
        "real_rate": rate_doc.get("real_rate"),
        "rate_normal": rate_doc.get("rate_normal"),
        "rate_vip": rate_doc.get("rate_vip"),
        "avg_profit_pct": 0.0,
    }


def _role_bucket_for(order: dict) -> str:
    return "vip" if order.get("user_role") in ("vip", "admin") else "normal"


async def _accumulate_revenue_order(
    o: dict, rate_doc: dict, fx: dict,
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


@router.get("/admin/revenue")
async def admin_revenue(request: Request, days: Optional[int] = None):
    await require_admin(request)
    q = {"status": {"$in": ["approved", "completed"]}}
    if days and days > 0:
        cutoff = (now_utc() - timedelta(days=days)).isoformat()
        q["updated_at"] = {"$gte": cutoff}

    orders = await db.orders.find(q, {"_id": 0}).to_list(5000)
    rates = await db.rates.find({}, {"_id": 0}).to_list(500)
    rate_by_pair = {(r["from_code"], r["to_code"]): r for r in rates}
    fx = await build_rate_lookup()

    by_pair: dict = {}
    by_role = {"normal": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0},
               "vip": {"profit_usdt": 0.0, "orders": 0, "volume_usdt": 0.0}}
    missing_rate_pairs: set = set()
    total_profit_usdt = 0.0
    total_volume_usdt = 0.0

    for o in orders:
        rate_doc = rate_by_pair.get((o["from_code"], o["to_code"]))
        vol, prof = await _accumulate_revenue_order(
            o, rate_doc, fx, by_pair, by_role, missing_rate_pairs,
        )
        total_volume_usdt += vol
        if prof is not None:
            total_profit_usdt += prof

    pair_items = _finalize_pair_items(by_pair)

    for r in by_role.values():
        r["profit_usdt"] = round(r["profit_usdt"], 4)
        r["volume_usdt"] = round(r["volume_usdt"], 4)

    marketplace = await _compute_marketplace_revenue(days)

    return {
        "total_profit_usdt": round(total_profit_usdt + marketplace["total_profit_usd"], 4),
        "p2p_profit_usdt": round(total_profit_usdt, 4),
        "marketplace_profit_usdt": round(marketplace["total_profit_usd"], 4),
        "total_volume_usdt": round(total_volume_usdt, 4),
        "profit_margin_pct": round((total_profit_usdt / total_volume_usdt * 100), 3) if total_volume_usdt > 0 else 0.0,
        "by_pair": pair_items,
        "by_role": by_role,
        "marketplace": marketplace,
        "missing_real_rate_pairs": sorted(missing_rate_pairs),
        "orders_total": len(orders),
    }


async def build_revenue_timeseries(granularity: str, days: Optional[int] = None,
                                    year: Optional[int] = None, month: Optional[int] = None):
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

    orders = await db.orders.find(order_q, {"_id": 0}).to_list(5000)
    redemptions = await db.redemptions.find(redemption_q, {"_id": 0}).to_list(5000)
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

    return build_buckets(orders, redemptions, profit_map, granularity)


@router.get("/admin/revenue/timeseries")
async def admin_revenue_timeseries(request: Request, granularity: str = "day",
                                     days: Optional[int] = None):
    await require_admin(request)
    if granularity not in ("day", "month"):
        raise HTTPException(status_code=400, detail="granularity inválida (day|month)")
    rows = await build_revenue_timeseries(granularity, days=days)
    return {"granularity": granularity, "rows": rows}


@router.get("/admin/revenue/monthly/export")
async def admin_revenue_monthly_export(request: Request, year: int, month: int,
                                          format: str = "csv"):
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

    totals = {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }
    payload = revenue_monthly_pdf(rows_asc, period_label, totals)
    headers = {"Content-Disposition": f'attachment; filename="ganancia-{period_label}.pdf"'}
    return Response(content=payload, media_type="application/pdf", headers=headers)


@router.post("/admin/revenue/monthly/send-now")
async def admin_revenue_send_now(payload: dict, request: Request):
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
    totals = {
        "p2p": sum(r["p2p_profit_usdt"] for r in rows_asc),
        "marketplace": sum(r["marketplace_profit_usdt"] for r in rows_asc),
        "total": sum(r["total_profit_usdt"] for r in rows_asc),
        "volume": sum(r["volume_usdt"] for r in rows_asc),
        "orders": sum(r["orders"] for r in rows_asc),
    }
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
