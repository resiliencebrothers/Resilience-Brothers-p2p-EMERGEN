"""Núcleo compartido de la Caja de Efectivo: fondos, denominaciones y balance.

Extraído de routes/cash_boxes.py (review iter270) para que los servicios
(cash_box_arqueo, cash_box_sync) no dependan de módulos de rutas.
"""
from typing import Dict

from db_client import db

FUNDS = ("CUP", "USD")
DENOMS: Dict[str, list] = {
    "CUP": [5000, 2000, 1000, 500, 200, 100, 50, 20, 10, 5, 3, 1],
    "USD": [100, 50, 20, 10, 5, 2, 1],
}


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
