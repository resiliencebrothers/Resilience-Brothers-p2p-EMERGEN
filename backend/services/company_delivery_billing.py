"""Ciclo económico de la mensajería de Empresa (Fase 4).

Modelo (elegido por el usuario):
- Tarifa FIJA por envío, configurable por el admin
  (`settings.global.company_delivery_fee_usdt`, en USDT).
- Al CREAR la solicitud se RETIENE la tarifa del sub-saldo USDT de la Empresa
  (débito idempotente por op_id). Sin saldo suficiente → se rechaza la creación.
- Si la solicitud se CANCELA antes de completarse, se REEMBOLSA íntegra
  (burn/undo del mismo débito; idempotente, exactamente una vez).
- Al CONFIRMARSE la entrega, el mensajero cobra su parte por el mecanismo
  EXISTENTE de entregas (`courier_share_usdt`) y Resilience RETIENE la comisión
  (`platform_share_usdt` = tarifa − parte del mensajero). El reparto usa el
  `courier_share_pct` global (comisión de Resilience = 100 − courier_share_pct).

No se credita la comisión a ninguna billetera: es el margen de la plataforma y
queda registrado en el documento de la entrega (`platform_share_paid_usdt`),
igual que el resto de la mensajería.
"""
from typing import Optional

from db_client import db
from services.balances import debit_balance_idempotent, burn_or_undo_debit

FEE_CODE = "USDT"


async def get_company_delivery_fee() -> float:
    """Tarifa fija vigente (USDT). 0 = mensajería gratuita hasta que el admin
    la configure."""
    doc = await db.settings.find_one(
        {"id": "global"}, {"_id": 0, "company_delivery_fee_usdt": 1}) or {}
    raw = doc.get("company_delivery_fee_usdt")
    try:
        return max(0.0, round(float(raw), 2)) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fee_op(reqid: str) -> str:
    return f"cdeliv-fee:{reqid}"


async def hold_fee(company_id: str, reqid: str, fee: float) -> str:
    """Retiene (débito idempotente) la tarifa del sub-saldo de la Empresa.
    Devuelve 'applied' | 'duplicate' | 'insufficient'. fee<=0 → 'applied'."""
    if fee <= 0:
        return "applied"
    return await debit_balance_idempotent(
        company_id, FEE_CODE, round(float(fee), 2), _fee_op(reqid))


async def refund_fee(company_id: str, reqid: str, fee: float) -> None:
    """Reembolsa la tarifa retenida (idempotente, exactamente una vez).
    No-op si fee<=0 (burn/undo tolera un débito que nunca llegó a aplicarse)."""
    if fee <= 0:
        return
    await burn_or_undo_debit(
        company_id, FEE_CODE, round(float(fee), 2), _fee_op(reqid))
