"""Liquidación de la operación vinculada a una entrega de mensajería.

Inversión de dependencias (code review): services/deliveries.py llamaba
directamente a funciones de routes/deposits.py y routes/admin_withdrawals.py,
creando el ciclo services → routes → services. Ahora esos módulos registran
aquí sus handlers al importarse (server.py importa todas las routes al
arrancar) y services/deliveries.py solo conoce este módulo.
"""
import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

_handlers: Dict[str, Callable[[str, dict], Awaitable[Any]]] = {}


def register_settlement_handler(
    kind: str, fn: Callable[[str, dict], Awaitable[Any]],
) -> None:
    _handlers[kind] = fn


async def settle_linked_operation(kind: str, ref_id: str, actor: dict) -> None:
    """Sincroniza la operación vinculada (retiro cash → paid, depósito cash
    → confirmado) tras confirmarse la entrega. No-op para kinds sin handler."""
    fn = _handlers.get(kind)
    if fn is None:
        return
    await fn(ref_id, actor)
