"""Market router — iter31. Currencies + Exchange rates + Products.

Endpoints:
- GET    /currencies                       (public)
- GET    /currencies/{code}/delivery-methods (public, iter43)
- GET    /currencies/{code}/receivable      (public, iter75)
- POST   /admin/currencies
- PUT    /admin/currencies/{currency_id}
- DELETE /admin/currencies/{currency_id}
- GET    /rates                            (public)
- POST   /admin/rates                      (upsert)
- PUT    /admin/rates/{rate_id}            (+ TOTP + margin-scan side effect)
- DELETE /admin/rates/{rate_id}
- GET    /products                         (active only)
- POST   /admin/products
- PUT    /admin/products/{product_id}
- DELETE /admin/products/{product_id}

Catalog models (Currency, ExchangeRate, Product) are defined here and
re-exported via server.py for legacy callers (the seed endpoint uses them).
"""
import uuid
import logging
import math
import re
from typing import Optional, Literal, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo.errors import DuplicateKeyError

from db_client import db
from services.conversions import snap_value
from auth_utils import (
    require_permission,
    _enforce_employee_currency_scope, _enforce_totp_step_up,
    get_session_user,
    now_utc, iso,
)
from audit_log import log_action
from services.delivery_rules import allowed_delivery_methods


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Market"])


# ============================================================
# Models
# ============================================================

class Currency(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    code: str
    name: str
    type: Literal["crypto", "fiat"]
    symbol: Optional[str] = ""
    country: Optional[str] = ""
    is_active: bool = True
    payment_account: Optional[str] = ""
    # iter44 — admin-controlled override of the heuristic in
    # `services/delivery_rules.allowed_delivery_methods`. When set (non-empty),
    # this list wins over the name-based detection. Empty/None falls back to
    # the heuristic so existing currencies keep their behaviour.
    delivery_methods: Optional[list[Literal["transfer", "cash", "crypto"]]] = None
    # iter55.29 — admin-controlled flag: when False the currency is REJECTED
    # as destination in `POST /vip/convert` (the platform cannot SEND funds
    # in this currency — e.g. USD/Zelle is receive-only). Defaults to True
    # for backward compat so existing currencies keep working with zero admin
    # action. Does NOT affect P2P orders or withdrawals (those use their own
    # delivery_methods pipeline).
    is_convertible_to: bool = True
    created_at: str = Field(default_factory=lambda: iso(now_utc()))

    @field_validator("code", mode="before")
    @classmethod
    def _strip_code(cls, v: Any) -> Any:
        # iter55.3 — defensively trim whitespace so data-entry mistakes never
        # break catalog lookups downstream (see admin_company_funds validation).
        return v.strip().upper() if isinstance(v, str) else v


class CurrencyCreate(BaseModel):
    code: str
    name: str
    type: Literal["crypto", "fiat"]
    symbol: Optional[str] = ""
    country: Optional[str] = ""
    is_active: bool = True
    payment_account: Optional[str] = ""
    delivery_methods: Optional[list[Literal["transfer", "cash", "crypto"]]] = None
    is_convertible_to: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def _strip_code(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("code")
    @classmethod
    def _code_format(cls, v: str) -> str:
        # FX06 — formato único de códigos: 2-12 letras/números/guion bajo.
        # Sin vacíos, espacios ni puntos (el código es parte de rutas de
        # campos de MongoDB en los saldos).
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_]{1,11}", v or ""):
            raise ValueError(
                "código de moneda inválido: usa 2-12 letras, números o "
                "guion bajo (sin espacios ni puntos)")
        return v


class RateTier(BaseModel):
    """iter143 — amount tier: applies when amount_from >= min_amount. The
    tier with the highest matching min wins (see services/rate_tiers.py).
    FX03 — todos los valores deben ser positivos, finitos y acotados."""
    model_config = ConfigDict(extra="ignore")
    min_amount: float = Field(..., ge=0, le=1_000_000_000_000,
                              allow_inf_nan=False)
    rate_normal: float = Field(..., gt=0, le=1_000_000_000_000,
                               allow_inf_nan=False)
    rate_vip: float = Field(..., gt=0, le=1_000_000_000_000,
                            allow_inf_nan=False)
    real_rate: Optional[float] = Field(None, gt=0, le=1_000_000_000_000,
                                       allow_inf_nan=False)

    @field_validator("min_amount", "rate_normal", "rate_vip", "real_rate")
    @classmethod
    def _snap_tier(cls, v: Optional[float]) -> Optional[float]:
        return snap_value(v) if v is not None else v


class ExchangeRate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_code: str
    to_code: str
    rate_normal: float
    rate_vip: float
    real_rate: Optional[float] = None  # real market exit rate; used to compute revenue
    # iter287 — tasa de VENTA ÚNICA: precio al que la EMPRESA VENDE el
    # `from_code` de esta fila, IGUAL para todos los clientes (ej. fila
    # USD→CUP con compra 680/690 y venta 712 → convertir CUP→USD acredita
    # 1/712 USD por CUP). Vacío = se usa la mayor tasa de compra (sin
    # margen adicional, pero nunca por debajo del precio de compra).
    rate_sell: Optional[float] = None
    tiers: Optional[list[RateTier]] = None  # iter143 — amount-tiered overrides
    updated_at: str = Field(default_factory=lambda: iso(now_utc()))


class ExchangeRateCreate(BaseModel):
    # FX03 — tasas positivas, finitas y acotadas; FX07 — códigos normalizados.
    from_code: str
    to_code: str
    rate_normal: float = Field(..., gt=0, le=1_000_000_000_000,
                               allow_inf_nan=False)
    rate_vip: float = Field(..., gt=0, le=1_000_000_000_000,
                            allow_inf_nan=False)
    real_rate: Optional[float] = Field(None, gt=0, le=1_000_000_000_000,
                                       allow_inf_nan=False)
    rate_sell: Optional[float] = Field(None, gt=0, le=1_000_000_000_000,
                                       allow_inf_nan=False)
    tiers: Optional[list[RateTier]] = None
    totp_code: Optional[str] = Field(None, max_length=11)
    # Riesgo-negocio #1 (auditoría 22/09/2026) — una tasa de venta por debajo
    # de la de compra solo se guarda con esta decisión explícita del staff.
    allow_negative_margin: bool = False

    @field_validator("from_code", "to_code", mode="before")
    @classmethod
    def _norm_codes(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("from_code", "to_code")
    @classmethod
    def _code_format(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_]{1,11}", v or ""):
            raise ValueError("código de moneda inválido")
        return v

    @field_validator("rate_normal", "rate_vip", "real_rate", "rate_sell")
    @classmethod
    def _snap_rates(cls, v: Optional[float]) -> Optional[float]:
        # FX03 — el valor se guarda sin ruido float (183.96700000000044
        # introducido por aritmética previa → 183.967).
        return snap_value(v) if v is not None else v

    @model_validator(mode="after")
    def _distinct_pair(self) -> "ExchangeRateCreate":
        if self.from_code == self.to_code:
            raise ValueError("las monedas de origen y destino deben ser diferentes")
        return self


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    image_url: str = ""
    price_usd: float
    cost_usd: float = 0.0
    stock: int = 0
    category: str = "general"
    is_active: bool = True
    # iter217 — marketplace multivendedor: productos de clientes VIP.
    # owner_id vacío = producto de la empresa (entra al inventario físico).
    owner_id: str = ""
    owner_name: str = ""
    approval_status: Literal["approved", "pending", "rejected"] = "approved"
    rejection_reason: str = ""
    # iter236 — sucursales donde está disponible (vacío = todas).
    available_store_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: iso(now_utc()))


class ProductCreate(BaseModel):
    name: str
    description: str = ""
    image_url: str = ""
    # iter247 — ge=0 bloquea precios/costos/stock negativos (corrupción contable).
    price_usd: float = Field(..., ge=0, le=1_000_000_000)
    cost_usd: float = Field(0.0, ge=0, le=1_000_000_000)
    stock: int = Field(0, ge=0, le=1_000_000)
    category: str = "general"
    is_active: bool = True
    available_store_ids: list[str] = Field(default_factory=list)


# ============================================================
# Currencies
# ============================================================

@router.get("/currencies")
async def list_currencies() -> Any:
    # iter55.3 — normalise stored codes on read so legacy rows with trailing
    # spaces (e.g. `"CUP "`) do not break frontend dropdowns or downstream
    # lookups (see admin_company_funds.create_company_fund_adjustment).
    rows = await db.currencies.find({}, {"_id": 0}).to_list(500)
    for r in rows:
        if isinstance(r.get("code"), str):
            r["code"] = r["code"].strip().upper()
    return rows


@router.get("/currencies/{code}/delivery-methods")
async def get_currency_delivery_methods(code: str) -> Any:
    """Public — source of truth for the frontend dropdown filter.

    Returns the list of physical delivery methods allowed for receiving the
    given destination currency, computed via `services.delivery_rules`:
      1. explicit `delivery_methods=[…]` set on the currency document, OR
      2. heuristic by `type` + name (`CUPT — transferencia` → `["transfer"]`).

    `accumulate` is intentionally NOT included in the response — it is always
    permitted (role-gated to VIP at order-creation time) and represents the
    "keep as balance" branch with no physical delivery.

    404 if the currency code does not exist.
    """
    norm = code.strip().upper()
    currency = await _find_currency_lenient(norm)
    if not currency:
        raise HTTPException(status_code=404, detail=f"Currency '{code}' not found")
    return {
        "code": norm,
        "type": currency.get("type"),
        "name": currency.get("name"),
        "allowed": allowed_delivery_methods(currency),
    }


@router.get("/currencies/{code}/receivable")
async def get_currency_receivable(code: str) -> Any:
    """iter75 — Whitelist of destination currencies the client can select
    when the source currency is `code`. Strictly directional: only pairs
    with an *explicit* `from_code == code` rate entry are returned. The
    inverse (`to_code → from_code`) is deliberately NOT considered — this
    matches the operator's decision to keep exchanges one-way for pairs
    that lack a configured inverse (e.g. USDT ⇄ ZELLE is only USDT → ZELLE).

    Returns 404 if the currency does not exist, otherwise:
        {
          "code": "USDT",
          "receivable": ["USD","CUPT","CUP",...],     # canonical destinations
          "count": 3
        }

    Notes:
      - Includes every `to_code` even if the currency doc is inactive at
        display time. The frontend still filters against `currencies` (which
        already excludes inactive ones), so an inactive destination will not
        surface in the UI — this way the endpoint stays a *pure* mirror of
        the rate table and can be reused by future admin tooling.
      - Ordering is stable: the client-side dropdown picks the first item as
        the default when the previously-selected destination is filtered
        out, so we sort alphabetically for a predictable UX.
    """
    norm = code.strip().upper()
    currency = await _find_currency_lenient(norm)
    if not currency:
        raise HTTPException(status_code=404, detail=f"Currency '{code}' not found")
    codes = await db.rates.distinct("to_code", {"from_code": norm})
    receivable = sorted({c.strip().upper() for c in codes if c})
    return {
        "code": norm,
        "receivable": receivable,
        "count": len(receivable),
    }



async def _find_currency_lenient(code: str) -> Optional[dict]:
    """iter55.3 — resilient currency lookup that survives trailing-whitespace
    data corruption in the `code` column. Falls back to a case-insensitive
    regex that also matches ` code ` (surrounding whitespace)."""
    norm = code.strip().upper()
    hit = await db.currencies.find_one({"code": norm}, {"_id": 0})
    if hit:
        return hit
    # Escape regex special chars and match trimmed
    import re
    pattern = f"^\\s*{re.escape(norm)}\\s*$"
    return await db.currencies.find_one(
        {"code": {"$regex": pattern, "$options": "i"}}, {"_id": 0}
    )


@router.post("/admin/currencies")
async def create_currency(payload: CurrencyCreate, request: Request) -> Any:
    await require_permission(request, "currencies")
    c = Currency(**payload.model_dump())
    try:
        await db.currencies.insert_one(c.model_dump())
    except DuplicateKeyError:
        # FX06 — índice único sobre el código canónico.
        raise HTTPException(status_code=409,
                            detail=f"Ya existe la moneda {c.code}.")
    return c.model_dump()


async def _currency_references(code: str) -> str:
    """FX06 — referencias financieras de un código de moneda (tasas y saldos
    de clientes). Vacío cuando no hay ninguna."""
    rates_n = await db.rates.count_documents(
        {"$or": [{"from_code": code}, {"to_code": code}]})
    bal_n = await db.users.count_documents({f"vip_balances.{code}": {"$gt": 0}})
    if code == "USD":
        bal_n += await db.users.count_documents({"vip_balance_usd": {"$gt": 0}})
    parts = []
    if rates_n:
        parts.append(f"{rates_n} tasa(s)")
    if bal_n:
        parts.append(f"{bal_n} cliente(s) con saldo")
    return ", ".join(parts)


@router.put("/admin/currencies/{currency_id}")
async def update_currency(currency_id: str, payload: CurrencyCreate, request: Request) -> Any:
    await require_permission(request, "currencies")
    existing = await db.currencies.find_one({"id": currency_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Moneda no encontrada")
    old_code = str(existing.get("code") or "").strip().upper()
    if payload.code != old_code:
        # FX06 — el código es la IDENTIDAD monetaria: con referencias
        # financieras es inmutable (renombrarlo dejaría saldos y tasas
        # huérfanos bajo el código antiguo).
        refs = await _currency_references(old_code)
        if refs:
            raise HTTPException(status_code=409, detail=(
                f"No se puede cambiar el código {old_code}: tiene "
                f"referencias financieras ({refs}). Crea una moneda nueva "
                "y desactiva esta."))
    try:
        await db.currencies.update_one({"id": currency_id},
                                       {"$set": payload.model_dump()})
    except DuplicateKeyError:
        raise HTTPException(status_code=409,
                            detail=f"Ya existe la moneda {payload.code}.")
    return await db.currencies.find_one({"id": currency_id}, {"_id": 0})


@router.delete("/admin/currencies/{currency_id}")
async def delete_currency(currency_id: str, request: Request) -> Any:
    await require_permission(request, "currencies")
    existing = await db.currencies.find_one({"id": currency_id}, {"_id": 0})
    if existing:
        code = str(existing.get("code") or "").strip().upper()
        refs = await _currency_references(code)
        if refs:
            # FX06 — retirar una moneda usada = desactivación controlada.
            raise HTTPException(status_code=409, detail=(
                f"No se puede eliminar {code}: tiene referencias "
                f"financieras ({refs}). Desactívala en su lugar."))
    await db.currencies.delete_one({"id": currency_id})
    return {"ok": True}


# ============================================================
# Exchange rates
# ============================================================

def _rate_convert_for_role(doc: dict, role: str) -> Optional[float]:
    """iter287 — tasa de conversión DIRECTA (la empresa COMPRA el from_code
    al cliente): por nivel. Espejo del tier picker de
    `routes/orders.py::vip_convert::_pick_tier_rate`."""
    key = "rate_vip" if role in ("vip", "admin") else "rate_normal"
    v = doc.get(key)
    return float(v) if v is not None else None


def _rate_sell_effective(doc: dict) -> Optional[float]:
    """iter287 — tasa de VENTA única de la empresa (igual para todos los
    niveles). Se aplica cuando el cliente ADQUIERE `from_code` de esta fila
    (conversión inversa). Sin configurar → la mayor tasa de compra."""
    from services.balances import effective_sell_rate
    v = effective_sell_rate(doc)
    return v if v > 0 else None


def _scrub_rate_for_client(doc: dict, role: str) -> dict:
    """Strip competitively-sensitive fields (`real_rate`, raw sell tiers)
    from a rate row before sending it to non-staff clients, and inject the
    pre-computed `rate_convert` + `rate_convert_sell` so the client-side
    converter preview stays correct without ever seeing the raw margin."""
    hidden = {"real_rate", "rate_sell_normal", "rate_sell_vip"}
    clean = {k: v for k, v in doc.items() if k not in hidden}
    if isinstance(clean.get("tiers"), list):
        clean["tiers"] = [
            {k: v for k, v in t.items() if k != "real_rate"}
            for t in clean["tiers"] if isinstance(t, dict)
        ]
    clean["rate_convert"] = _rate_convert_for_role(doc, role)
    clean["rate_convert_sell"] = _rate_sell_effective(doc)
    return clean


@router.get("/rates")
async def list_rates(request: Request) -> Any:
    """Public rate list.

    iter101.1 — `real_rate` is the operator's real market exit rate and
    encodes the platform's profit margin. Exposing it to normal/VIP
    clients is a competitive leak, so we scrub it here and inject a
    pre-computed `rate_convert` field (server-side tier picker) so the
    self-conversion preview stays accurate. Admins + employees keep the
    raw `real_rate` since they need it to audit revenue and edit rates.
    """
    docs = await db.rates.find({}, {"_id": 0}).to_list(500)
    session_user = await get_session_user(request)
    role = (session_user or {}).get("role", "anonymous")
    if role in ("admin", "employee"):
        # Staff sees everything as-is (admin dashboard, revenue analytics,
        # rate editor all read `real_rate`). Still add `rate_convert` so
        # the converter widget's tier picker works even for admin/vip
        # clients using their own dashboard as clients (unlikely but safe).
        return [
            {**d,
             "rate_convert": _rate_convert_for_role(d, role),
             "rate_convert_sell": _rate_sell_effective(d)} for d in docs
        ]
    return [_scrub_rate_for_client(d, role) for d in docs]


def _rate_values_changed(existing: dict, payload: ExchangeRateCreate) -> bool:
    """FX01 — ¿el guardado cambia algún valor del par existente?"""
    def _f(v: Any) -> Optional[float]:
        return None if v is None else float(v)
    new_tiers = [t.model_dump() for t in (payload.tiers or [])]
    old_tiers = [
        {"min_amount": float(t.get("min_amount") or 0),
         "rate_normal": _f(t.get("rate_normal")),
         "rate_vip": _f(t.get("rate_vip")),
         "real_rate": _f(t.get("real_rate"))}
        for t in (existing.get("tiers") or []) if isinstance(t, dict)]
    return (
        _f(existing.get("rate_normal")) != payload.rate_normal
        or _f(existing.get("rate_vip")) != payload.rate_vip
        or _f(existing.get("real_rate")) != payload.real_rate
        or _f(existing.get("rate_sell")) != payload.rate_sell
        or old_tiers != new_tiers
    )


def _assert_margin_policy(payload: ExchangeRateCreate) -> None:
    """Riesgo-negocio #1 (auditoría 22/09/2026) — VENTA por debajo de COMPRA:
    con `rate_sell < max(compra)` un cliente gana convirtiendo ida y vuelta.
    Se exige la decisión explícita `allow_negative_margin=true`."""
    if payload.rate_sell is None or payload.allow_negative_margin:
        return
    max_buy = max(payload.rate_normal, payload.rate_vip)
    if payload.rate_sell < max_buy - 1e-12:
        raise HTTPException(status_code=422, detail={
            "code": "NEGATIVE_MARGIN",
            "message": (
                f"La tasa de venta ({payload.rate_sell:g}) es inferior a la "
                f"de compra ({max_buy:g}): un cliente ganaría convirtiendo "
                "ida y vuelta. Si es una promoción deliberada, marca "
                "'permitir tasa promocional con pérdida' y guarda de nuevo."),
        })


async def _maybe_alert_margin_risks(actor: dict, payload: ExchangeRateCreate,
                                    fresh: dict) -> None:
    """Alerta (no bloqueante) a los admins: promoción con pérdida autorizada
    y/o ciclo rentable entre el par y su inverso."""
    warnings: list[str] = []
    max_buy = max(payload.rate_normal, payload.rate_vip)
    if payload.rate_sell is not None and payload.rate_sell < max_buy - 1e-12:
        warnings.append(
            f"venta {payload.rate_sell:g} < compra {max_buy:g} en "
            f"{fresh['from_code']}→{fresh['to_code']} (promoción con pérdida "
            f"autorizada por {actor.get('name') or actor.get('email')})")
    inv = await db.rates.find_one(
        {"from_code": fresh["to_code"], "to_code": fresh["from_code"]},
        {"_id": 0, "rate_normal": 1, "rate_vip": 1})
    if inv:
        try:
            inv_buy = max(float(inv.get("rate_normal") or 0),
                          float(inv.get("rate_vip") or 0))
        except (TypeError, ValueError):
            inv_buy = 0.0
        cycle = max_buy * inv_buy
        if math.isfinite(cycle) and cycle > 1 + 1e-9:
            warnings.append(
                f"ciclo {fresh['from_code']}→{fresh['to_code']}→"
                f"{fresh['from_code']} con factor {cycle:.6f} > 1: las tasas "
                "de compra combinadas permiten un beneficio en círculo")
    if warnings:
        try:
            from admin_alerts import notify_all_admins
            await notify_all_admins(
                db, title="⚠️ Margen de tasas en revisión",
                body="; ".join(warnings), url_path="/admin/rates")
        except Exception as e:  # noqa: BLE001
            logger.error(f"margin alert failed: {e}")


async def _persist_rate(actor: dict, payload: ExchangeRateCreate,
                        existing: Optional[dict]) -> dict:
    """FX01/FX07/FX08 — mutación CENTRAL de tasas: misma validación,
    escritura atómica frente al índice único, mismo evento y misma auditoría
    para creación, upsert y edición."""
    _assert_margin_policy(payload)
    rate_data = payload.model_dump(exclude={"totp_code", "allow_negative_margin"})
    old = existing
    if existing:
        try:
            await db.rates.update_one(
                {"id": existing["id"]},
                {"$set": {**rate_data, "updated_at": iso(now_utc())}})
        except DuplicateKeyError:
            raise HTTPException(status_code=409,
                                detail="Ya existe una tasa para ese par.")
        fresh = await db.rates.find_one({"id": existing["id"]}, {"_id": 0})
    else:
        r = ExchangeRate(**rate_data)
        try:
            await db.rates.insert_one(r.model_dump())
            fresh = r.model_dump()
        except DuplicateKeyError:
            # FX07 — carrera de creación: el índice único arbitra. RF03 — el
            # perdedor pasa a ser una EDICIÓN del par recién creado: exige la
            # MISMA confirmación 2FA que cualquier cambio de precio existente
            # (antes actualizaba sin código).
            row = await db.rates.find_one(
                {"from_code": payload.from_code, "to_code": payload.to_code},
                {"_id": 0})
            if not row:
                raise HTTPException(status_code=409,
                                    detail="Conflicto al crear la tasa; reintenta.")
            old = row
            if _rate_values_changed(row, payload):
                await _enforce_totp_step_up(actor, payload.totp_code,
                                            action_label="actualizar tasa")
            await db.rates.update_one(
                {"id": row["id"]},
                {"$set": {**rate_data, "updated_at": iso(now_utc())}})
            fresh = await db.rates.find_one({"id": row["id"]}, {"_id": 0})
    # FX08 — el evento lleva SOLO id/updated_at: cada cliente recarga su
    # versión autorizada vía GET /rates (jamás el documento interno con
    # `real_rate` y tramos crudos).
    try:
        from services.live_bus import publish as live_publish
        await live_publish("rates_updated", {
            "rate_id": fresh["id"], "updated_at": fresh.get("updated_at")})
    except Exception as e:
        logger.error(f"Rate SSE publish failed: {e}")
    try:
        await _scan_rate_change_margin(old, fresh)
    except Exception as e:
        logger.error(f"Rate margin scan failed: {e}")
    try:
        await _fanout_rate_change_push(old, fresh)
    except Exception as e:
        logger.error(f"Rate change push fanout failed: {e}")
    await log_action(
        db, actor, "rate.update" if old else "rate.create", "rate",
        fresh["id"],
        summary=(f"Tasa {fresh['from_code']}→{fresh['to_code']} "
                 f"{'actualizada' if old else 'creada'}"),
        details={"old": old, "new": fresh},
    )
    await _maybe_alert_margin_risks(actor, payload, fresh)
    return fresh


@router.post("/admin/rates")
async def create_rate(payload: ExchangeRateCreate, request: Request) -> Any:
    # FX01 — misma autorización que PUT: permiso específico de tasas (antes
    # bastaba ser staff, lo que permitía editar precios sin el permiso).
    actor = await require_permission(request, "rates")
    _enforce_employee_currency_scope(actor, payload.from_code, payload.to_code)
    existing = await db.rates.find_one(
        {"from_code": payload.from_code, "to_code": payload.to_code}, {"_id": 0}
    )
    if existing and _rate_values_changed(existing, payload):
        # FX01 — cambiar un precio existente exige el mismo código de
        # confirmación 2FA que PUT, por CUALQUIER vía.
        await _enforce_totp_step_up(actor, payload.totp_code,
                                    action_label="actualizar tasa")
    return await _persist_rate(actor, payload, existing)


@router.put("/admin/rates/{rate_id}")
async def update_rate(rate_id: str, payload: ExchangeRateCreate, request: Request) -> Any:
    actor = await require_permission(request, "rates")
    await _enforce_totp_step_up(actor, payload.totp_code, action_label="actualizar tasa")
    _enforce_employee_currency_scope(actor, payload.from_code, payload.to_code)
    old = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    if not old:
        raise HTTPException(status_code=404, detail="Tasa no encontrada")
    _enforce_employee_currency_scope(actor, old["from_code"], old["to_code"])
    if (payload.from_code, payload.to_code) != (old["from_code"], old["to_code"]):
        # FX07 — PUT no puede transformar un par en otro ya existente.
        clash = await db.rates.find_one(
            {"from_code": payload.from_code, "to_code": payload.to_code,
             "id": {"$ne": rate_id}}, {"_id": 1})
        if clash:
            raise HTTPException(status_code=409,
                                detail="Ya existe una tasa para ese par.")
    return await _persist_rate(actor, payload, old)


async def _rate_fanout_inapp(
    clients: list, from_code: str, to_code: str,
    old_normal: float, old_vip: float, new_normal: float, new_vip: float,
) -> int:
    """Insert an in-app `rate_change` notification for every active client.
    Returns the number of notifications successfully inserted."""
    from routes.notifications import _insert_notification
    from services.notification_i18n import t as _t, get_field
    inapp_created = 0
    for u in clients:
        rate = new_vip if u["role"] == "vip" else new_normal
        lang = u.get("preferred_language")
        vip_suffix = get_field("rate_change", lang, "vip_suffix") if u["role"] == "vip" else ""
        try:
            await _insert_notification(
                recipient_user_id=u["user_id"],
                type="rate_change",
                title=_t("rate_change", lang, "title", from_code=from_code, to_code=to_code),
                message=_t(
                    "rate_change", lang, "message",
                    from_code=from_code, to_code=to_code, rate=rate, vip_suffix=vip_suffix,
                ),
                data={
                    "from_code": from_code, "to_code": to_code,
                    "rate_normal": new_normal, "rate_vip": new_vip,
                    "old_rate_normal": old_normal, "old_rate_vip": old_vip,
                },
            )
            inapp_created += 1
        except Exception as e:  # noqa: BLE001
            logger.error(f"[rate-fanout] inapp insert failed for {u.get('user_id')}: {e}")
    return inapp_created


async def _rate_fanout_push(
    role_by_id: dict, from_code: str, to_code: str,
    new_normal: float, new_vip: float,
    lang_by_id: Optional[dict] = None,
) -> tuple[int, int, int]:
    """Push the new rate to every subscribed device belonging to an active
    vip/normal client. Prunes dead subscriptions. Returns (sent, skipped, dead).
    `lang_by_id` maps user_id → preferred_language so each device gets the
    payload rendered in the recipient's chosen language."""
    from push_service import build_rate_changed_payload, send_push
    subs = await db.push_subscriptions.find({}, {"_id": 0}).to_list(5000)
    dead_ids: list[str] = []
    sent, skipped, dead = 0, 0, 0
    for sub in subs:
        uid = sub.get("user_id")
        role = role_by_id.get(uid)
        if role not in ("vip", "normal"):
            skipped += 1
            continue
        lang = (lang_by_id or {}).get(uid)
        payload = build_rate_changed_payload(
            from_code, to_code, new_normal, new_vip, for_role=role, lang=lang,
        )
        result = send_push(sub.get("subscription"), payload)
        if result == "dead":
            dead_ids.append(sub["id"])
            dead += 1
        elif result == "ok":
            sent += 1
        else:  # disabled / transient
            skipped += 1
    if dead_ids:
        await db.push_subscriptions.delete_many({"id": {"$in": dead_ids}})
    return sent, skipped, dead


async def _fanout_rate_change_push(old: Optional[dict], fresh: Optional[dict]) -> None:
    """Notify every client (role vip/normal) about the rate change via BOTH:
    1) In-app notification (`db.notifications`) — every active client gets it,
       whether or not they subscribed to push.
    2) Web Push — only devices that opted in through the bell toggle.
    Skipped when neither `rate_normal` nor `rate_vip` moved."""
    if not fresh:
        logger.info("[rate-fanout] skipped: no fresh rate")
        return
    pair = f"{fresh.get('from_code')}→{fresh.get('to_code')}"
    old_normal = float((old or {}).get("rate_normal") or 0.0)
    old_vip = float((old or {}).get("rate_vip") or 0.0)
    new_normal = float(fresh.get("rate_normal") or 0.0)
    new_vip = float(fresh.get("rate_vip") or 0.0)
    if new_normal == old_normal and new_vip == old_vip:
        logger.info(f"[rate-fanout] {pair}: no-op (rates unchanged)")
        return

    from_code, to_code = fresh["from_code"], fresh["to_code"]
    clients = await db.users.find(
        {"role": {"$in": ["vip", "normal"]}, "account_status": {"$ne": "suspended"}},
        {"_id": 0, "user_id": 1, "role": 1, "preferred_language": 1},
    ).to_list(20000)

    inapp_created = await _rate_fanout_inapp(
        clients, from_code, to_code, old_normal, old_vip, new_normal, new_vip,
    )
    role_by_id = {u["user_id"]: u["role"] for u in clients}
    lang_by_id = {u["user_id"]: u.get("preferred_language") for u in clients}
    sent, skipped, dead = await _rate_fanout_push(
        role_by_id, from_code, to_code, new_normal, new_vip, lang_by_id=lang_by_id,
    )
    logger.info(
        f"[rate-fanout] {pair}: clients={len(clients)} inapp={inapp_created} "
        f"push_sent={sent} push_dead_pruned={dead} push_skipped={skipped} "
        f"delta_normal={old_normal}→{new_normal} delta_vip={old_vip}→{new_vip}"
    )


async def _scan_rate_change_margin(old: Optional[dict], fresh: Optional[dict]) -> Any:
    """When the real_rate of a pair changes, fan out a warning if any pending
    orders for that pair would now generate a loss."""
    if not fresh or fresh.get("real_rate") is None:
        return
    old_rr = old.get("real_rate") if old else None
    if fresh.get("real_rate") == old_rr:
        return
    from services.orders_helpers import compute_order_profit
    from admin_alerts import notify_all_admins
    pending = await db.orders.find(
        {"from_code": fresh["from_code"], "to_code": fresh["to_code"], "status": "pending"},
        {"_id": 0},
    ).to_list(500)
    losers, total_loss = [], 0.0
    for o in pending:
        p = await compute_order_profit(o, fresh)
        if p and p["amount"] < 0:
            losers.append(o)
            total_loss += abs(p["amount"])
    if losers:
        await notify_all_admins(
            db,
            title=f"⚠️ {len(losers)} órdenes pendientes en pérdida",
            body=(
                f"Actualizaste la tasa real de {fresh['from_code']}→{fresh['to_code']} a "
                f"{fresh['real_rate']}. {len(losers)} órdenes pendientes generarían pérdida total "
                f"≈ {total_loss:.2f} {fresh['to_code']}."
            ),
            url_path="/admin/orders",
        )


@router.delete("/admin/rates/{rate_id}")
async def delete_rate(rate_id: str, request: Request) -> Any:
    actor = await require_permission(request, "rates")
    existing = await db.rates.find_one({"id": rate_id}, {"_id": 0})
    if existing:
        _enforce_employee_currency_scope(actor, existing["from_code"], existing["to_code"])
    await db.rates.delete_one({"id": rate_id})
    # iter97 — SSE fan-out on delete so exchange screens drop the row.
    try:
        from services.live_bus import publish as live_publish
        await live_publish("rates_updated", {"rate_id": rate_id, "deleted": True})
    except Exception as e:
        logger.error(f"Rate SSE publish failed: {e}")
    return {"ok": True}


# ============================================================
# Products
# ============================================================

@router.get("/products")
async def list_products(request: Request) -> Any:
    # iter217 — solo productos aprobados salen al marketplace (los de
    # vendedores VIP nacen 'pending' hasta que un admin los aprueba).
    rows = await db.products.find(
        {"is_active": True,
         "$or": [{"approval_status": {"$exists": False}},
                 {"approval_status": "approved"}]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(500)
    # iter229 — precios de la tienda en CUP efectivo → USDT a la tasa vigente
    # según el rol del que mira: VIP (mayorista) rate_vip, resto rate_normal.
    from auth_utils import get_session_user
    from services.marketplace_fx import augment_products_fx
    user = await get_session_user(request)
    return await augment_products_fx(rows, role=(user or {}).get("role"))


def _check_employee_product_perms(actor: dict, *, editing_price: bool, editing_image: bool) -> Any:
    """iter21 — admin bypasses. Employees need explicit toggles set in /admin/users."""
    if actor.get("role") == "admin":
        return
    if editing_price and not actor.get("can_edit_product_prices"):
        raise HTTPException(status_code=403, detail="No tienes permiso para modificar precios de productos")
    if editing_image and not actor.get("can_upload_product_images"):
        raise HTTPException(status_code=403, detail="No tienes permiso para subir imágenes de productos")


@router.get("/admin/products")
async def admin_list_products(request: Request) -> Any:
    """iter223 — listado para gestión: TODOS los productos de la empresa,
    incluidos los inactivos (el endpoint público /products solo muestra
    activos, por eso el operador no veía los importados del Excel)."""
    await require_permission(request, "products")
    rows = await db.products.find(
        {"$or": [{"owner_id": {"$in": [None, ""]}},
                 {"owner_id": {"$exists": False}}]}, {"_id": 0}) \
        .sort("name", 1).to_list(1000)
    from services.marketplace_fx import augment_products_fx
    return await augment_products_fx(rows, role="vip")


@router.post("/admin/products/{product_id}/toggle-active")
async def toggle_product_active(product_id: str, request: Request) -> Any:
    """iter223 — publica/oculta un producto en el marketplace con un clic."""
    actor = await require_permission(request, "products")
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    new_state = not bool(doc.get("is_active", True))
    await db.products.update_one({"id": product_id},
                                 {"$set": {"is_active": new_state}})
    await log_action(db, actor, "product.toggle_active", "product", product_id,
                     summary=f"{'Publicado' if new_state else 'Oculto'}: {doc.get('name', '')}")
    try:
        from services.live_bus import publish
        await publish("products_changed", {"product_id": product_id})
    except Exception as e:
        logger.error(f"products_changed publish failed: {e}")
    return {"id": product_id, "is_active": new_state}


def _norm_product_name(s: str) -> str:
    """iter226 — nombre normalizado (sin acentos/mayúsculas/espacios extra)."""
    import unicodedata
    s = unicodedata.normalize("NFD", (s or "").strip().lower())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


async def _find_duplicate_company_product(name: str) -> Any:
    target = _norm_product_name(name)
    if not target:
        return None
    rows = await db.products.find(
        {"$or": [{"owner_id": {"$in": [None, ""]}},
                 {"owner_id": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    for r in rows:
        if _norm_product_name(r.get("name", "")) == target:
            return r
    return None


@router.post("/admin/products")
async def create_product(payload: ProductCreate, request: Request) -> Any:
    actor = await require_permission(request, "products")
    _check_employee_product_perms(
        actor,
        editing_price=(payload.price_usd is not None and payload.price_usd != 0)
                       or (payload.cost_usd is not None and payload.cost_usd != 0),
        editing_image=bool((payload.image_url or "").strip()),
    )
    # iter226 — evita duplicados: si la mercancía ya existe se debe registrar
    # una Entrada para que las estadísticas se acumulen en el mismo producto.
    dup = await _find_duplicate_company_product(payload.name)
    if dup:
        raise HTTPException(status_code=409, detail=(
            f"Ya existe «{dup.get('name', '')}» en el inventario. "
            "Regístralo como Entrada (reponer existente) para sumar unidades "
            "y mantener sus estadísticas en el mismo producto."))
    p = Product(**payload.model_dump())
    # iter219 — la imagen puede llegar como data URL (subida directa) → R2.
    from services.proof_upload import maybe_upload_proof
    p.image_url = maybe_upload_proof(p.image_url, "products") or ""
    await db.products.insert_one(p.model_dump())
    # iter226 — el stock inicial queda auditado como Entrada en el registro.
    if int(p.stock or 0) > 0:
        try:
            from services.inventory import record_movement
            await record_movement(
                product=p.model_dump(), mtype="entrada", quantity=int(p.stock),
                unit_cost=float(p.cost_usd or 0),
                note="Stock inicial al crear el producto",
                source="alta", actor=actor, apply_stock=False)
        except Exception as e:  # noqa: BLE001
            logger.error(f"initial stock entrada failed: {e}")
    return p.model_dump()


@router.put("/admin/products/{product_id}")
async def update_product(product_id: str, payload: ProductCreate, request: Request) -> Any:
    actor = await require_permission(request, "products")
    existing = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    price_changed = (
        float(payload.price_usd) != float(existing.get("price_usd", 0))
        or float(payload.cost_usd) != float(existing.get("cost_usd", 0))
    )
    image_changed = (payload.image_url or "") != (existing.get("image_url") or "")
    _check_employee_product_perms(actor, editing_price=price_changed, editing_image=image_changed)
    data = payload.model_dump()
    from services.proof_upload import maybe_upload_proof
    data["image_url"] = maybe_upload_proof(data.get("image_url"), "products") or ""
    await db.products.update_one({"id": product_id}, {"$set": data})
    # iter219 — auditoría de precios + alerta de stock bajo tras edición manual.
    if not existing.get("owner_id"):
        try:
            from services.inventory import record_price_change, maybe_alert_low_stock
            new_price = float(payload.price_usd or 0)
            old_price = float(existing.get("price_usd") or 0)
            if new_price != old_price:
                await record_price_change(product=existing, field_label="Precio venta",
                                          old=old_price, new=new_price, actor=actor)
            new_cost = float(payload.cost_usd or 0)
            old_cost = float(existing.get("cost_usd") or 0)
            if new_cost != old_cost:
                await record_price_change(product=existing, field_label="Costo unitario",
                                          old=old_cost, new=new_cost, actor=actor)
            await maybe_alert_low_stock(product_id)
        except Exception as e:
            logger.error(f"price audit/low stock check after edit failed: {e}")
    return await db.products.find_one({"id": product_id}, {"_id": 0})


@router.delete("/admin/products/{product_id}")
async def delete_product(product_id: str, request: Request) -> Any:
    actor = await require_permission(request, "products")
    if actor.get("role") != "admin" and not actor.get("can_delete_products"):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar productos")
    await db.products.delete_one({"id": product_id})
    return {"ok": True}
