"""IPV (Inventario Físico) — Fase 2: costeo promedio ponderado (WAC) y
valoración histórica por lote.

- `compute_wac`  mezcla el costo existente con el de la nueva compra en vez de
  reemplazarlo por el último precio pagado (el margen de venta refleja el costo
  real combinado de la mercancía en existencia).
- `inventory_lots`  colección append-only: cada ENTRADA queda como un lote
  (fecha, costo unitario, cantidad) para trazabilidad y valoración histórica.
  Idempotente por `movement_id` (un movimiento de entrada = un lote).
- `build_valuation`  reporte de valoración: por producto → existencia, WAC,
  valor por WAC y valor por lotes (FIFO: la existencia restante corresponde a
  los lotes más recientes, porque los más antiguos se venden primero).

Decisión de diseño (aprobada por el operador): los lotes NO cambian el cálculo
del profit de venta (eso usa el WAC del producto); se usan solo para la
valoración histórica y la trazabilidad. La asignación FIFO se calcula en tiempo
de lectura, así que nunca se escribe en la ruta de venta idempotente ni hay
riesgo de descuadre con el stock.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from db_client import db
from auth_utils import now_utc, iso

logger = logging.getLogger(__name__)

_LOTS_INDEX_READY = False


def compute_wac(old_stock: int, old_cost: float, qty: int,
                entry_cost: float) -> float:
    """Costo promedio ponderado tras una entrada.

    nuevo = (existencia·costo_viejo + cantidad·costo_entrada) /
            (existencia + cantidad)

    Si no había existencia (o era negativa por corrupción), el costo pasa a ser
    el de la compra nueva. Redondeo a 4 decimales para no acumular error de
    centavos tras muchas entradas."""
    base = max(int(old_stock or 0), 0)
    q = int(qty or 0)
    oc = float(old_cost or 0)
    ec = float(entry_cost or 0)
    if q <= 0:
        return round(oc, 4)
    denom = base + q
    if denom <= 0:
        return round(ec, 4)
    return round((base * oc + q * ec) / denom, 4)


async def _ensure_lots_index() -> None:
    global _LOTS_INDEX_READY
    if not _LOTS_INDEX_READY:
        await db.inventory_lots.create_index("movement_id", unique=True,
                                             sparse=True)
        await db.inventory_lots.create_index([("product_id", 1),
                                              ("received_at", 1)])
        _LOTS_INDEX_READY = True


async def record_lot(product: dict, qty: int, unit_cost: float,
                     movement_id: str, source: str = "manual",
                     actor: Optional[dict] = None) -> Optional[dict]:
    """Registra un lote por cada entrada. Idempotente por `movement_id`."""
    await _ensure_lots_index()
    doc = {
        "id": str(uuid.uuid4()),
        "product_id": product["id"],
        "product_name": product.get("name", ""),
        "qty": int(qty),
        "unit_cost": round(float(unit_cost or 0), 4),
        "received_at": iso(now_utc()),
        "source": source,
        "movement_id": movement_id,
        "actor_id": (actor or {}).get("user_id", ""),
        "actor_email": (actor or {}).get("email", ""),
    }
    try:
        await db.inventory_lots.insert_one({**doc})
    except DuplicateKeyError:
        return None  # ya existía el lote de este movimiento
    return doc


def _lot_age_days(received_at: str, ref: datetime) -> Optional[int]:
    try:
        dt = datetime.fromisoformat(received_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((ref - dt).days, 0)
    except Exception:  # noqa: BLE001
        return None


async def build_valuation() -> dict:
    """Valoración del inventario de la empresa por producto y por lote.

    - `inventory_value_wac` = existencia × costo promedio ponderado.
    - `inventory_value_lots` = suma del valor de los lotes que aún sostienen la
      existencia (FIFO: se asignan los lotes más recientes a la existencia
      actual; los más antiguos se consideran ya vendidos).
    - `stock_sin_lote` = unidades sin historial de lote (p. ej. productos
      importados antes de la Fase 2): el operador ve cuánto stock aún no tiene
      trazabilidad por lote."""
    from services.inventory import build_control_rows
    rows = await build_control_rows()
    lots = await db.inventory_lots.find({}, {"_id": 0}) \
        .sort("received_at", 1).to_list(100000)
    lots_by: dict = {}
    for lot in lots:
        lots_by.setdefault(lot["product_id"], []).append(lot)

    ref = now_utc()
    out = []
    tot_val_wac = 0.0
    tot_val_lots = 0.0
    tot_units = 0
    tot_sin_lote = 0
    for r in rows:
        stock = int(r.get("stock") or 0)
        wac = float(r.get("cost_usd") or 0)
        val_wac = round(stock * wac, 2)
        plist = lots_by.get(r["product_id"], [])
        # FIFO: la existencia restante son los lotes MÁS RECIENTES.
        remaining = stock
        alloc: dict = {}
        for lot in reversed(plist):
            take = min(int(lot.get("qty") or 0), remaining) if remaining > 0 else 0
            alloc[lot["id"]] = take
            remaining -= take
        lot_rows = []
        val_lots = 0.0
        for lot in plist:
            rem = alloc.get(lot["id"], 0)
            rv = round(rem * float(lot.get("unit_cost") or 0), 2)
            val_lots += rv
            lot_rows.append({
                "id": lot["id"],
                "received_at": lot.get("received_at"),
                "unit_cost": float(lot.get("unit_cost") or 0),
                "qty": int(lot.get("qty") or 0),
                "remaining": rem,
                "remaining_value": rv,
                "age_days": _lot_age_days(lot.get("received_at") or "", ref),
                "source": lot.get("source", ""),
            })
        sin_lote = remaining if remaining > 0 else 0
        out.append({
            "product_id": r["product_id"],
            "name": r.get("name", ""),
            "category": r.get("category", ""),
            "is_active": bool(r.get("is_active", True)),
            "stock": stock,
            "price_usd": float(r.get("price_usd") or 0),
            "wac": round(wac, 4),
            "inventory_value_wac": val_wac,
            "inventory_value_lots": round(val_lots, 2),
            "stock_sin_lote": sin_lote,
            "num_lotes": len([x for x in lot_rows if x["remaining"] > 0]),
            "lots": lot_rows,
        })
        tot_val_wac += val_wac
        tot_val_lots += val_lots
        tot_units += stock
        tot_sin_lote += sin_lote
    out.sort(key=lambda x: x["inventory_value_wac"], reverse=True)
    return {
        "products": out,
        "totals": {
            "units": tot_units,
            "value_wac": round(tot_val_wac, 2),
            "value_lots": round(tot_val_lots, 2),
            "num_products": len(out),
            "stock_sin_lote": tot_sin_lote,
        },
    }
