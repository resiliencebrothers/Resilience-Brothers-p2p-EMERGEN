"""iter264 — Arqueo Programado de la Caja de Efectivo.

Al cierre del día (20:00 America/Havana) la caja pide el arqueo de billetes de
cada fondo de EMPRESA con actividad o balance y sin arqueo registrado hoy
(push + email + campana a los admins). Además, cada arqueo con faltante o
sobrante en una caja de empresa alerta a los admins al instante.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from db_client import db

logger = logging.getLogger(__name__)
_TZ = ZoneInfo("America/Havana")


def havana_day_start_utc() -> str:
    """Inicio del día actual en Cuba, como ISO UTC (comparable con created_at)."""
    now_local = datetime.now(timezone.utc).astimezone(_TZ)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).isoformat()


async def _alert_admins(title: str, body: str, *, ntype: str,
                        data: Dict[str, Any]) -> None:
    """Push + email + campana a todos los admins. Nunca lanza excepción."""
    try:
        from admin_alerts import notify_all_admins
        await notify_all_admins(db, title=title, body=body,
                                url_path="/dashboard/cashbox")
    except Exception as e:  # noqa: BLE001
        logger.error(f"arqueo push/email a admins falló: {e}")
    try:
        from routes.notifications import _insert_notification
        admins = await db.users.find({"role": "admin"},
                                     {"_id": 0, "user_id": 1}).to_list(50)
        for a in admins:
            await _insert_notification(
                recipient_user_id=a["user_id"], type=ntype,
                title=title, message=body, data=data)
    except Exception as e:  # noqa: BLE001
        logger.error(f"arqueo campana a admins falló: {e}")


async def notify_arqueo_discrepancy(box: Dict[str, Any],
                                    arqueo: Dict[str, Any]) -> None:
    """Alerta a los admins un arqueo con faltante/sobrante en caja de empresa."""
    if box.get("scope") != "empresa" or arqueo.get("status") == "cuadrada":
        return
    estado = str(arqueo.get("status") or "")
    fund = str(arqueo.get("fund") or "")
    diff = float(arqueo.get("difference") or 0)
    title = f"Arqueo con {estado}: {box.get('name')} ({fund})"
    body = (f"El arqueo de la caja «{box.get('name')}» (fondo {fund}) registró "
            f"un {estado.upper()} de {abs(diff):,.2f} {fund}.\n"
            f"Contado: {float(arqueo.get('total_counted') or 0):,.2f} {fund} · "
            f"Sistema: {float(arqueo.get('system_balance') or 0):,.2f} {fund}.\n"
            f"Registrado por {arqueo.get('created_by_name') or '—'}."
            + (f" Nota: {arqueo['note']}" if arqueo.get("note") else ""))
    await _alert_admins(title, body, ntype="cash_box_arqueo_diff",
                        data={"box_id": box.get("id"), "fund": fund,
                              "difference": diff,
                              "arqueo_id": arqueo.get("id")})


async def pending_arqueo_funds(box: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fondos de la caja con actividad hoy (o balance) y sin arqueo de hoy."""
    from routes.cash_boxes import FUNDS, _fund_balance
    day_start = havana_day_start_utc()
    pend: List[Dict[str, Any]] = []
    for fund in FUNDS:
        if await db.cash_box_arqueos.find_one(
                {"box_id": box["id"], "fund": fund,
                 "created_at": {"$gte": day_start}}, {"_id": 1}):
            continue
        movs_today = await db.cash_box_movements.count_documents(
            {"box_id": box["id"], "fund": fund,
             "created_at": {"$gte": day_start}})
        bal = await _fund_balance(box, fund)
        if movs_today or abs(bal) > 0.009:
            pend.append({"fund": fund, "balance": bal,
                         "movs_today": movs_today})
    return pend


async def run_daily_arqueo_request() -> int:
    """Pide a los admins el arqueo de cierre de cada fondo de empresa
    pendiente. Devuelve el nº de fondos avisados."""
    lines: List[str] = []
    async for box in db.cash_boxes.find(
            {"scope": "empresa", "is_active": {"$ne": False}}, {"_id": 0}):
        for p in await pending_arqueo_funds(box):
            lines.append(f"• {box['name']} — fondo {p['fund']}: balance "
                         f"sistema {p['balance']:,.2f} {p['fund']}")
    if not lines:
        return 0
    title = "Arqueo de cierre pendiente"
    body = ("La Caja de Efectivo pide el arqueo de billetes del cierre de hoy:\n"
            + "\n".join(lines)
            + "\n\nRegistra el conteo en Caja de Efectivo → Arqueo de caja. "
              "Se avisará si hay faltante o sobrante.")
    await _alert_admins(title, body, ntype="cash_box_arqueo_due",
                        data={"pending": len(lines)})
    return len(lines)
