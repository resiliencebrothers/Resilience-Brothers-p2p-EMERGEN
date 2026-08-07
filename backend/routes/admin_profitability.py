"""Admin router — profitability calculator (iter113).

Ports the operator's Excel "Calculadora USDT → CUP" (cash cycle logic):
  recovered        = sell_price × (1 + sell_pct/100) ÷ (1 + buy_pct/100)
  net_gain         = (recovered − buy_price) × qty
  conversion_gain  = (recovered − sell_price) × qty   (in cash units)
  profitability    = net_gain ÷ (buy_price × qty)
Percentages are stored as percent numbers (26 = 26%).

Collections:
  profitability_settings   {currency, buy_pct, sell_pct, updated_at}
  profitability_operations {id, op_date, client_name, currency, payment_currency,
                            quantity, sell_price, buy_price, buy_pct, sell_pct,
                            result_fx, conversion_gain, net_gain, profitability_pct,
                            status, note, actor_*, created_at}
Gated by the new `profitability` permission code.
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db_client import db
from auth_utils import require_permission, now_utc, iso
from audit_log import log_action

router = APIRouter(prefix="/admin/profitability", tags=["Admin"])


def _norm_code(c: Any) -> str:
    return c.strip().upper() if isinstance(c, str) else ""


def _compute(mode: str, sell_price: float, buy_price: float, buy_pct: float, sell_pct: float, quantity: float) -> Dict[str, float]:
    if mode == "direct":
        # Modo 1 — buy in cash, sell directly in transfer. buy_pct = transfer cost %.
        real_cost = buy_price * (1 + buy_pct / 100.0)
        conversion_gain = 0.0
        result_fx = (sell_price - real_cost) * quantity
        net_gain = result_fx
    else:
        # Modo 2 — full cash cycle: sell for cash, cash→transfer at sell_pct,
        # transfer→cash at buy_pct. Everything measured in cash units.
        recovered = sell_price * (1 + sell_pct / 100.0) / (1 + buy_pct / 100.0)
        real_cost = buy_price
        result_fx = (sell_price - buy_price) * quantity
        conversion_gain = (recovered - sell_price) * quantity
        net_gain = (recovered - buy_price) * quantity
    gross = sell_price * quantity if mode == "direct" else buy_price * quantity
    profitability_pct = (net_gain / gross * 100.0) if gross else 0.0
    return {
        "real_cost": round(real_cost, 4),
        "result_fx": round(result_fx, 4),
        "conversion_gain": round(conversion_gain, 4),
        "net_gain": round(net_gain, 4),
        "profitability_pct": round(profitability_pct, 4),
    }


class SettingItem(BaseModel):
    currency: str = Field(..., min_length=1, max_length=10)
    buy_pct: float = Field(..., ge=0, le=1000)
    sell_pct: float = Field(..., ge=0, le=1000)


class SettingsPayload(BaseModel):
    items: List[SettingItem] = Field(..., max_length=100)


class OperationCreate(BaseModel):
    op_date: str = Field(default="", max_length=10)
    client_name: str = Field(..., min_length=1, max_length=120)
    mode: str = Field(default="combined", pattern="^(direct|combined)$")
    currency: str = Field(..., min_length=1, max_length=10)
    payment_currency: str = Field(..., min_length=1, max_length=10)
    quantity: float = Field(..., gt=0, le=1_000_000_000)
    sell_price: float = Field(..., gt=0, le=1_000_000_000)
    buy_price: float = Field(..., ge=0, le=1_000_000_000)
    buy_pct: float = Field(default=0, ge=0, le=1000)
    sell_pct: float = Field(default=0, ge=0, le=1000)
    note: str = Field(default="", max_length=500)


@router.get("/settings")
async def get_profitability_settings(request: Request) -> Any:
    await require_permission(request, "profitability")
    rows = await db.profitability_settings.find({}, {"_id": 0}).to_list(200)
    return {"items": rows}


@router.put("/settings")
async def put_profitability_settings(payload: SettingsPayload, request: Request) -> Any:
    actor = await require_permission(request, "profitability")
    ts = iso(now_utc())
    saved = []
    for item in payload.items:
        code = _norm_code(item.currency)
        if not code:
            continue
        doc = {"currency": code, "buy_pct": item.buy_pct, "sell_pct": item.sell_pct, "updated_at": ts}
        await db.profitability_settings.update_one({"currency": code}, {"$set": doc}, upsert=True)
        saved.append(doc)
    await log_action(
        db, actor, "profitability.settings_update", "profitability_settings",
        summary=f"% transferencia actualizados para {len(saved)} moneda(s)",
        details={"items": saved},
    )
    return {"items": saved}


@router.get("/operations")
async def list_profitability_operations(
    request: Request,
    currency: Optional[str] = None,
    status_q: Optional[str] = None,
    limit: int = 500,
) -> Any:
    await require_permission(request, "profitability")
    query: Dict[str, Any] = {}
    if currency:
        query["currency"] = _norm_code(currency)
    if status_q in ("profitable", "loss"):
        query["status"] = status_q
    rows = await db.profitability_operations.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 1000))
    totals: Dict[str, Any] = {"count": len(rows), "profitable": 0, "loss": 0, "net_by_currency": {}}
    for r in rows:
        totals["profitable" if r.get("status") == "profitable" else "loss"] += 1
        pc = r.get("payment_currency", "?")
        totals["net_by_currency"][pc] = round(totals["net_by_currency"].get(pc, 0) + (r.get("net_gain") or 0), 4)
    return {"items": rows, "totals": totals}


@router.get("/operations.pdf")
async def export_profitability_pdf(
    request: Request,
    since: Optional[str] = None,
    until: Optional[str] = None,
    currency: Optional[str] = None,
) -> Any:
    """iter114 — Investor-ready PDF of the operations log with KPI cards,
    per-payment-currency gains and the full detail table."""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from profitability_pdf import generate_profitability_pdf

    actor = await require_permission(request, "profitability")
    query: Dict[str, Any] = {}
    if currency:
        query["currency"] = _norm_code(currency)
    date_q: Dict[str, str] = {}
    if since:
        date_q["$gte"] = since[:10]
    if until:
        date_q["$lte"] = until[:10]
    if date_q:
        query["op_date"] = date_q
    ops = await db.profitability_operations.find(query, {"_id": 0}).sort(
        [("op_date", -1), ("created_at", -1)]
    ).to_list(2000)

    by_cur: Dict[str, Dict[str, Any]] = {}
    profitable = 0
    for op in ops:
        if op.get("status") == "profitable":
            profitable += 1
        pc = op.get("payment_currency", "?")
        row = by_cur.setdefault(pc, {"currency": pc, "count": 0, "result_fx": 0.0, "conversion_gain": 0.0, "net_gain": 0.0})
        row["count"] += 1
        row["result_fx"] += op.get("result_fx") or 0
        row["conversion_gain"] += op.get("conversion_gain") or 0
        row["net_gain"] += op.get("net_gain") or 0
    currency_rows = sorted(by_cur.values(), key=lambda r: r["currency"])
    total = len(ops)
    kpis = {
        "total": total,
        "profitable": profitable,
        "loss": total - profitable,
        "success_rate": (profitable / total * 100.0) if total else 0.0,
    }
    pdf_bytes = generate_profitability_pdf(
        since=since or "", until=until or "",
        ops=ops, currency_rows=currency_rows, kpis=kpis, actor=actor,
    )
    await log_action(
        db, actor, "profitability.pdf_exported", "profitability_operation", "report",
        summary=f"Exported profitability PDF ({since or '—'} → {until or '—'}, {total} ops)",
    )
    slug = f"_{since}_{until}" if since and until else (f"_{since or until}" if (since or until) else "")
    ts = now_utc().strftime("%Y%m%d_%H%M")
    filename = f"rentabilidad{slug}_{ts}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/operations")
async def create_profitability_operation(payload: OperationCreate, request: Request) -> Any:
    actor = await require_permission(request, "profitability")
    sell_pct = 0.0 if payload.mode == "direct" else payload.sell_pct
    computed = _compute(payload.mode, payload.sell_price, payload.buy_price, payload.buy_pct, sell_pct, payload.quantity)
    op = {
        "id": str(uuid.uuid4()),
        "op_date": payload.op_date or iso(now_utc())[:10],
        "client_name": payload.client_name.strip(),
        "mode": payload.mode,
        "currency": _norm_code(payload.currency),
        "payment_currency": _norm_code(payload.payment_currency),
        "quantity": payload.quantity,
        "sell_price": payload.sell_price,
        "buy_price": payload.buy_price,
        "buy_pct": payload.buy_pct,
        "sell_pct": sell_pct,
        **computed,
        "status": "profitable" if computed["net_gain"] >= 0 else "loss",
        "note": payload.note.strip(),
        "actor_id": actor.get("id", ""),
        "actor_email": actor.get("email", ""),
        "actor_name": actor.get("name", ""),
        "created_at": iso(now_utc()),
    }
    await db.profitability_operations.insert_one({**op})
    await log_action(
        db, actor, "profitability.op_create", "profitability_operation", op["id"],
        summary=f"Operación {op['currency']}→{op['payment_currency']} cliente '{op['client_name']}' neta {op['net_gain']}",
    )
    return op


@router.delete("/operations/{op_id}")
async def delete_profitability_operation(op_id: str, request: Request) -> Any:
    actor = await require_permission(request, "profitability")
    existing = await db.profitability_operations.find_one({"id": op_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Operación no encontrada")
    await db.profitability_operations.delete_one({"id": op_id})
    await log_action(
        db, actor, "profitability.op_delete", "profitability_operation", op_id,
        summary=f"Operación eliminada — cliente '{existing.get('client_name')}'",
    )
    return {"ok": True}
