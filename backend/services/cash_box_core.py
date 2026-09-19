"""Núcleo compartido de la Caja de Efectivo: fondos, denominaciones y balance.

Extraído de routes/cash_boxes.py (review iter270) para que los servicios
(cash_box_arqueo, cash_box_sync) no dependan de módulos de rutas.
"""
from typing import Dict

from db_client import db

FUNDS = ("CUP", "USD")
# iter277 — listas de fábrica compartidas; las vigentes (con extras del
# admin) se obtienen de services.denominations.get_cash_denominations().
from services.denominations import DEFAULT_CASH_DENOMINATIONS  # noqa: E402

DENOMS: Dict[str, list] = {k: list(v)
                           for k, v in DEFAULT_CASH_DENOMINATIONS.items()}


async def fund_balance(box: dict, fund: str) -> float:
    """Balance del fondo: inicial + entradas − salidas (agregación, sin tope)."""
    initial = float(((box.get("initial") or {}).get(fund) or {}).get("amount") or 0)
    pipe = [
        {"$match": {"box_id": box["id"], "fund": fund}},
        {"$group": {"_id": "$type", "total": {"$sum": "$amount"}}},
    ]
    tot = {r["_id"]: float(r["total"]) async for r in
           db.cash_box_movements.aggregate(pipe)}
    return round(initial + tot.get("entrada", 0.0) - tot.get("salida", 0.0), 2)
