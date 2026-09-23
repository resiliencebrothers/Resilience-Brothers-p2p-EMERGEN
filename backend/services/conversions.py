"""Auditoría de monedas 22/09/2026 — FX04/FX05/FX09/FX10/FX11.

Registro financiero DURABLE de conversiones (`db.conversions`), cotización
ejecutable ÚNICA para el convertidor y el barrido, precisión por moneda con
redondeo hacia abajo y guardas de catálogo compartidas.

Decisiones de negocio registradas (22/09/2026):
- Los tramos por importe (`tiers`) aplican SOLO a órdenes P2P; el convertidor
  de saldos usa siempre la tasa base.
- Una moneda desactivada SÍ puede liquidarse como ORIGEN hacia monedas
  activas; como DESTINO queda bloqueada (debe existir, estar activa y ser
  convertible).
"""
import logging
import math
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Context, Decimal, ROUND_FLOOR, ROUND_HALF_EVEN
from typing import Any, Optional

from fastapi import HTTPException

from db_client import db
from services.balances import effective_sell_rate

logger = logging.getLogger(__name__)

# Marcadores de conversión conservados en el doc del usuario para que el
# sanador distinga "aplicada" de "nunca ejecutada" (FX09).
CONVERSION_MARKER_CAP = 40


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# FX11 — precisión por moneda y redondeo SIEMPRE hacia abajo
# ============================================================

def currency_decimals(doc: Optional[dict], code: str = "") -> int:
    """Decimales de liquidación: campo explícito `decimals` (0..12) o, por
    defecto, 8 para cripto (unidades pequeñas como BTC) y 4 para fiat/USDT
    (compatibilidad con los saldos existentes)."""
    d = doc or {}
    raw = d.get("decimals")
    if isinstance(raw, (int, float)) and 0 <= int(raw) <= 12:
        return int(raw)
    c = str(d.get("code") or code or "").upper()
    if c == "USDT":
        return 4
    return 8 if d.get("type") == "crypto" else 4


# Ajuste a 15 dígitos significativos ANTES de truncar: elimina el ruido de
# 1-2 ulp de la aritmética float (p.ej. 1/0.00001 → 99999.99999999999) sin
# tocar restos genuinos, que siempre viven muy por encima del dígito 15.
_SNAP_CTX = Context(prec=15, rounding=ROUND_HALF_EVEN)


def snap_value(value: float) -> float:
    """Elimina ruido float de 1-2 ulp (183.96700000000044 → 183.967)."""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return float("nan")
    return float(_SNAP_CTX.plus(Decimal(repr(float(value)))))


def floor_amount(value: float, decimals: int) -> float:
    """Redondeo hacia abajo con aritmética decimal: una ida y vuelta jamás
    crea valor por redondeo, y un resultado < unidad mínima queda en 0
    (el caller lo rechaza sin mover saldos)."""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return float("nan")
    q = Decimal(1).scaleb(-decimals)
    snapped = Decimal(repr(snap_value(value)))
    return float(snapped.quantize(q, rounding=ROUND_FLOOR))


def sufficiency_epsilon(amount: float) -> float:
    """RF04 — tolerancia RELATIVA de suficiencia de saldo: cubre ~1 ulp de
    ruido float sin acercarse jamás a una unidad mínima — imposible gastar
    saldo inexistente en monedas de unidades pequeñas (BTC)."""
    return abs(float(amount)) * 1e-9 + 1e-12


async def get_destination_decimals(code: str) -> int:
    doc = await db.currencies.find_one({"code": code}, {"_id": 0})
    return currency_decimals(doc, code)


# ============================================================
# FX05 — guardas de catálogo compartidas por ambos convertidores
# ============================================================

async def assert_convertible_destination(to_code: str) -> dict:
    """El DESTINO debe existir en el catálogo, estar activo y ser
    convertible. El ORIGEN no se valida aquí: política explícita — un saldo
    en moneda desactivada puede liquidarse hacia monedas activas."""
    doc = await db.currencies.find_one({"code": to_code}, {"_id": 0})
    if not doc or doc.get("is_active", True) is False:
        raise HTTPException(status_code=400, detail=(
            f"La moneda {to_code} no está disponible como destino de "
            "conversión (no existe en el catálogo o está desactivada)."))
    if doc.get("is_convertible_to", True) is False:
        raise HTTPException(status_code=400, detail=(
            f"La plataforma no puede enviar {to_code} — no está disponible "
            "como destino de conversión. Elige otra moneda de destino."))
    return doc


# ============================================================
# FX04 — cotización EJECUTABLE única (convertidor y barrido)
# ============================================================

def _finite_pos(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


async def build_pair_docs() -> dict:
    """{(FROM, TO): doc} de la tabla de tasas (una fila por par — el índice
    único lo garantiza; ver services/rates_catalog)."""
    docs = await db.rates.find({}, {"_id": 0}).to_list(1000)
    return {(str(d.get("from_code") or "").strip().upper(),
             str(d.get("to_code") or "").strip().upper()): d for d in docs}


def quote_convert_rate(role: str, from_code: str, to_code: str,
                       pair_docs: dict) -> Optional[float]:
    """Tasa EJECUTABLE de conversión de saldo — idéntica para el convertidor
    normal y el barrido de saldos pequeños (FX04):
      • Fila directa from→to: la empresa COMPRA `from_code` → tasa de compra
        por nivel (VIP/admin → rate_vip, resto → rate_normal). Tasa BASE:
        los tramos aplican SOLO a órdenes P2P (decisión de negocio).
      • Solo fila inversa to→from: el cliente ADQUIERE `to_code` → tasa de
        VENTA única de la empresa (1/effective_sell).
    Sin ruta configurada → None: JAMÁS se inventa una paridad USD=USDT para
    ejecutar (la valoración informativa vive aparte en services/balances)."""
    key = "rate_vip" if role in ("vip", "admin") else "rate_normal"
    direct = pair_docs.get((from_code, to_code))
    if direct:
        v = _finite_pos(direct.get(key))
        if v:
            return v
    inverse = pair_docs.get((to_code, from_code))
    if inverse:
        sell = _finite_pos(effective_sell_rate(inverse))
        if sell:
            return 1.0 / sell
    return None


# ============================================================
# FX09 — registro durable, idempotencia y sanador
# ============================================================

async def ensure_conversion_indexes() -> None:
    await db.conversions.create_index("id", unique=True)
    # Idempotencia por op_id: índice PARCIAL (solo docs con op_id) — un
    # índice sparse compuesto indexaría también los docs sin op_id y
    # bloquearía la segunda conversión normal del mismo usuario.
    try:
        await db.conversions.drop_index("user_id_1_op_id_1")
    except Exception:  # noqa: BLE001 — no existía o ya migrado
        pass
    await db.conversions.create_index(
        [("user_id", 1), ("op_id", 1)], unique=True, name="uniq_user_op",
        partialFilterExpression={"op_id": {"$exists": True}})
    await db.conversions.create_index([("user_id", 1), ("created_at", -1)])
    await db.conversions.create_index([("status", 1), ("created_at", 1)])
    await db.conversions.create_index("marker_id")


async def find_conversion_by_op(user_id: str, op_id: str) -> Optional[dict]:
    return await db.conversions.find_one(
        {"user_id": user_id, "op_id": op_id}, {"_id": 0})


async def record_conversion(*, user: dict, kind: str, from_code: str,
                            to_code: str, amount_from: float,
                            amount_to: float, rate: float, usdt_fee: float,
                            amount_from_usdt: float, marker_id: str,
                            op_id: Optional[str] = None, batch_id: str = "",
                            batch_size: int = 0, batch_index: int = 0) -> dict:
    """Inserta el registro durable ANTES de mover saldos (status=applying).
    Si esta inserción falla, la operación no se ejecuta: nunca puede haber
    dinero movido sin registro financiero recuperable (FX09).
    RF01 — cada conversión recibe un marcador ÚNICO no vacío; solo un
    barrido comparte marcador entre SUS propias filas (mismo usuario)."""
    marker = marker_id or f"cmk_{uuid.uuid4().hex}"
    doc: dict = {
        "id": f"conv_{uuid.uuid4().hex}",
        "user_id": user["user_id"],
        "user_name": user.get("name") or "",
        "user_email": user.get("email") or "",
        "kind": kind,
        "from_code": from_code, "to_code": to_code,
        "amount_from": amount_from, "amount_to": amount_to,
        "rate": rate, "usdt_fee": usdt_fee,
        "amount_from_usdt": amount_from_usdt,
        "marker_id": marker,
        "status": "applying",
        "created_at": iso_now(),
    }
    if op_id:
        doc["op_id"] = op_id
    if batch_id:
        doc.update({"batch_id": batch_id, "batch_size": batch_size,
                    "batch_index": batch_index})
    await db.conversions.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


def marker_pipeline_stage(marker_id: str) -> dict:
    """Etapa de pipeline que anexa el marcador al doc del usuario DENTRO de
    la misma actualización atómica que mueve los saldos. RF01 — SIN recorte
    ciego: la prueba durable solo se retira cuando su registro está resuelto
    (ver `compact_conversion_markers`)."""
    return {"$set": {"recent_conversion_ids": {"$concatArrays": [
        {"$ifNull": ["$recent_conversion_ids", []]}, [marker_id]]}}}


def marker_push_update(marker_id: str) -> dict:
    """Operador `$push` equivalente para actualizaciones no-pipeline."""
    return {"recent_conversion_ids": {"$each": [marker_id]}}


async def mark_conversions(user_id: str, marker_id: str, status: str) -> None:
    """RF01 — el sellado está condicionado por USUARIO y marcador: la
    confirmación de una conversión jamás alcanza registros ajenos, y un
    marcador vacío no puede sellar nada en bloque."""
    if not marker_id:
        return
    await db.conversions.update_many(
        {"user_id": user_id, "marker_id": marker_id, "status": "applying"},
        {"$set": {"status": status, "resolved_at": iso_now()}})


async def heal_pending_conversions(max_age_seconds: int = 600) -> int:
    """Resuelve conversiones que quedaron en `applying` (proceso caído entre
    el registro y la actualización de saldo). Como el movimiento de saldos es
    UNA actualización atómica que además escribe el marcador, la membresía
    del marcador en `recent_conversion_ids` decide sin ambigüedad:
    presente → applied; ausente → failed (no se movió dinero)."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=max_age_seconds)).isoformat()
    rows = await db.conversions.find(
        {"status": "applying", "created_at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "user_id": 1, "marker_id": 1}).to_list(500)
    healed = 0
    seen: set = set()
    for c in rows:
        mid = c.get("marker_id") or ""
        if not mid or mid in seen:
            continue
        seen.add(mid)
        u = await db.users.find_one({"user_id": c["user_id"]},
                                    {"_id": 0, "recent_conversion_ids": 1})
        applied = mid in ((u or {}).get("recent_conversion_ids") or [])
        await mark_conversions(c["user_id"], mid,
                               "applied" if applied else "failed")
        logger.warning("conversión %s resuelta por sanador: %s",
                       mid, "applied" if applied else "failed")
        healed += 1
    # RF01 — compactación SEGURA del registro embebido (nunca expulsa la
    # prueba de una conversión aún pendiente).
    healed += await compact_conversion_markers()
    return healed


async def compact_conversion_markers(batch: int = 50) -> int:
    """RF01 — sustituye al viejo `$slice` ciego: del arreglo
    `recent_conversion_ids` solo se retiran marcadores cuyos registros están
    RESUELTOS (o ya no existen). Un marcador con conversión `applying` JAMÁS
    se expulsa — es la prueba durable con la que el sanador decide
    applied/failed; 40+ operaciones posteriores no pueden convertir en
    'fallida' una operación ya ejecutada."""
    users = await db.users.find(
        {f"recent_conversion_ids.{CONVERSION_MARKER_CAP}": {"$exists": True}},
        {"_id": 0, "user_id": 1, "recent_conversion_ids": 1}).to_list(batch)
    n = 0
    for u in users:
        markers = u.get("recent_conversion_ids") or []
        excess = len(markers) - CONVERSION_MARKER_CAP
        if excess <= 0:
            continue
        candidates = markers[:excess]
        pending = set(await db.conversions.distinct(
            "marker_id", {"marker_id": {"$in": candidates},
                          "status": "applying"}))
        removable = [m for m in candidates if m not in pending]
        if removable:
            await db.users.update_one(
                {"user_id": u["user_id"]},
                {"$pullAll": {"recent_conversion_ids": removable}})
            n += 1
    return n
