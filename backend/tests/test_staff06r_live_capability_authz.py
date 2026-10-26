"""STAFF-06-R (auditoría residual) — el feed SSE debe autorizar los eventos
OPERATIVOS de staff por CAPACIDAD + ÁMBITO DE MONEDA, no solo por rol.

Retirar un permiso (p. ej. 'orders') tiene que cortar order_created /
order_status_changed aunque el empleado conserve el rol 'employee' y la cuenta
activa. Los eventos personales del cliente (user_id=...) quedan SEPARADOS del
feed operativo. La revocación en caliente (update_authz) corta el feed desde el
siguiente evento, sin necesidad de reconectar.

Tests unitarios directos sobre services.live_bus (deterministas, en proceso).
"""
import asyncio
import pytest

from services.live_bus import (
    subscribe as bus_subscribe,
    unsubscribe as bus_unsubscribe,
    publish as bus_publish,
    update_authz,
)


async def _got(sub) -> bool:
    try:
        await asyncio.wait_for(sub.queue.get(), 0.2)
        return True
    except asyncio.TimeoutError:
        return False


# ------------------------------------------------------------------
# Capacidad: retirar el permiso corta el feed (caso central del informe)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_order_feed_requires_orders_permission():
    s_admin = await bus_subscribe("s06r_admin", role="admin")
    s_with = await bus_subscribe("s06r_emp_with", role="employee",
                                 allowed_permissions=["orders"])
    s_without = await bus_subscribe("s06r_emp_without", role="employee",
                                    allowed_permissions=["support", "kyc"])
    s_empty = await bus_subscribe("s06r_emp_empty", role="employee",
                                  allowed_permissions=[])
    try:
        await bus_publish("order_status_changed",
                          {"order_id": "o1", "amount_from": 99, "from_code": "USD",
                           "to_code": "CUP"},
                          roles=("admin", "employee"))
        assert await _got(s_admin) is True      # admin ve todo
        assert await _got(s_with) is True        # empleado CON 'orders'
        assert await _got(s_without) is False    # empleado SIN 'orders' → NO
        assert await _got(s_empty) is False      # deny-by-default
    finally:
        for s in (s_admin, s_with, s_without, s_empty):
            await bus_unsubscribe(s)


@pytest.mark.asyncio
async def test_revocation_in_flight_stops_feed_without_reconnect():
    # Misma suscripción VIVA: tras update_authz quitando 'orders', el bus deja
    # de entregarle el evento (simula la revalidación periódica de live.py).
    sub = await bus_subscribe("s06r_revoke", role="employee",
                              allowed_permissions=["orders"])
    try:
        await bus_publish("order_created", {"id": "o1", "from_code": "USD",
                                            "to_code": "CUP"},
                          roles=("admin", "employee"))
        assert await _got(sub) is True
        # Revocación en caliente (rol intacto, cuenta activa, SIN reconectar).
        update_authz(sub, "employee", [], [])
        await bus_publish("order_created", {"id": "o2", "from_code": "USD",
                                            "to_code": "CUP"},
                          roles=("admin", "employee"))
        assert await _got(sub) is False
    finally:
        await bus_unsubscribe(sub)


# ------------------------------------------------------------------
# Ámbito de moneda (igual que los filtros REST; solo empleados; vacío = todas)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_currency_scope_filters_staff_events():
    s_usd = await bus_subscribe("s06r_usd", role="employee",
                                allowed_permissions=["orders"],
                                allowed_currencies=["USD"])
    s_all = await bus_subscribe("s06r_allcur", role="employee",
                                allowed_permissions=["orders"],
                                allowed_currencies=[])
    try:
        # Orden que toca USD → el empleado USD la recibe.
        await bus_publish("order_status_changed",
                          {"order_id": "o1", "from_code": "USD", "to_code": "CUP"},
                          roles=("admin", "employee"))
        assert await _got(s_usd) is True
        assert await _got(s_all) is True
        # Orden EUR→GBP (ninguna en su ámbito) → el empleado USD NO la recibe;
        # el de ámbito vacío (todas) sí.
        await bus_publish("order_status_changed",
                          {"order_id": "o2", "from_code": "EUR", "to_code": "GBP"},
                          roles=("admin", "employee"))
        assert await _got(s_usd) is False
        assert await _got(s_all) is True
    finally:
        await bus_unsubscribe(s_usd)
        await bus_unsubscribe(s_all)


@pytest.mark.asyncio
async def test_currencyless_event_bypasses_scope():
    # ledger_changed no declara moneda → el ámbito no lo filtra (solo exige el
    # permiso 'transactions').
    s_scoped = await bus_subscribe("s06r_ledger", role="employee",
                                   allowed_permissions=["transactions"],
                                   allowed_currencies=["USD"])
    s_noperm = await bus_subscribe("s06r_ledger_np", role="employee",
                                   allowed_permissions=["orders"],
                                   allowed_currencies=[])
    try:
        await bus_publish("ledger_changed", {"reason": "order", "order_id": "o1"},
                          roles=("admin", "employee"))
        assert await _got(s_scoped) is True       # tiene 'transactions'
        assert await _got(s_noperm) is False       # no tiene 'transactions'
    finally:
        await bus_unsubscribe(s_scoped)
        await bus_unsubscribe(s_noperm)


# ------------------------------------------------------------------
# Mapeo por evento: withdrawals / deposits / support
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_withdrawal_and_deposit_require_withdrawals_cap():
    s_w = await bus_subscribe("s06r_w", role="employee",
                              allowed_permissions=["withdrawals"])
    s_other = await bus_subscribe("s06r_w_other", role="employee",
                                  allowed_permissions=["orders"])
    try:
        for ev in ("withdrawal_created", "withdrawal_status_changed", "deposit_created"):
            await bus_publish(ev, {"id": "x", "amount": 99, "currency": "USD"},
                              roles=("admin", "employee"))
            assert await _got(s_w) is True, ev
            assert await _got(s_other) is False, ev
    finally:
        await bus_unsubscribe(s_w)
        await bus_unsubscribe(s_other)


@pytest.mark.asyncio
async def test_support_feed_requires_support_cap():
    s_sup = await bus_subscribe("s06r_sup", role="employee",
                                allowed_permissions=["support"])
    s_no = await bus_subscribe("s06r_sup_no", role="employee",
                               allowed_permissions=["orders"])
    try:
        await bus_publish("support_ticket_updated",
                          {"ticket_id": "t1", "status": "answered"},
                          roles=("admin", "employee"))
        assert await _got(s_sup) is True
        assert await _got(s_no) is False
    finally:
        await bus_unsubscribe(s_sup)
        await bus_unsubscribe(s_no)


# ------------------------------------------------------------------
# Separación cliente/staff + broadcast público + fail-closed
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_personal_feed_not_capability_gated():
    # El DUEÑO de la orden (cliente normal, sin permisos de staff) recibe su
    # propio order_status_changed vía user_id — feed personal, separado.
    owner = await bus_subscribe("s06r_owner", role="normal")
    try:
        await bus_publish("order_status_changed",
                          {"order_id": "o1", "from_code": "USD", "to_code": "CUP"},
                          user_id="s06r_owner")
        assert await _got(owner) is True
    finally:
        await bus_unsubscribe(owner)


@pytest.mark.asyncio
async def test_public_broadcast_unaffected():
    emp = await bus_subscribe("s06r_pub_emp", role="employee",
                              allowed_permissions=[])
    nrm = await bus_subscribe("s06r_pub_nrm", role="normal")
    try:
        await bus_publish("rates_updated", {"rate_id": "r1"})  # sin roles → todos
        assert await _got(emp) is True
        assert await _got(nrm) is True
    finally:
        await bus_unsubscribe(emp)
        await bus_unsubscribe(nrm)


@pytest.mark.asyncio
async def test_unmapped_staff_event_fail_closed_for_employee_admin_still_gets_it():
    s_admin = await bus_subscribe("s06r_unmapped_admin", role="admin")
    s_emp = await bus_subscribe("s06r_unmapped_emp", role="employee",
                                allowed_permissions=["orders", "withdrawals",
                                                     "support", "transactions"])
    try:
        await bus_publish("some_brand_new_staff_event", {"x": 1},
                          roles=("admin", "employee"))
        assert await _got(s_admin) is True      # admin ve todo (sin fuga)
        assert await _got(s_emp) is False        # fail-closed hasta mapearlo
    finally:
        await bus_unsubscribe(s_admin)
        await bus_unsubscribe(s_emp)


@pytest.mark.asyncio
async def test_explicit_require_perm_override():
    # require_perm explícito tiene prioridad sobre la matriz.
    s_ok = await bus_subscribe("s06r_ov_ok", role="employee",
                               allowed_permissions=["kyc"])
    s_no = await bus_subscribe("s06r_ov_no", role="employee",
                               allowed_permissions=["orders"])
    try:
        await bus_publish("ledger_changed", {"reason": "x"},
                          roles=("admin", "employee"), require_perm="kyc")
        assert await _got(s_ok) is True
        assert await _got(s_no) is False
    finally:
        await bus_unsubscribe(s_ok)
        await bus_unsubscribe(s_no)
