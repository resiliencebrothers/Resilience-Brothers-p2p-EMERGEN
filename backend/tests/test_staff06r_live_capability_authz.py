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
    reauthorize_event,
    event_iterator,
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


# ------------------------------------------------------------------
# STAFF-06-R2 — eventos PENDIENTES re-autorizados en la ENTREGA FINAL
# ------------------------------------------------------------------
# Un evento encolado bajo el snapshot ANTERIOR (publish usa el snapshot vigente)
# NO debe salir si el permiso se retira mientras el evento está pendiente en
# cualquiera de las dos colas. La compuerta final `reauthorize_event` lo descarta.

async def _drain(sub):
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


@pytest.mark.asyncio
async def test_staff06r2_pending_staff_event_dropped_after_revocation():
    # R01 — evento pendiente en Subscription.queue tras revocar el permiso.
    sub = await bus_subscribe("s06r2_a", role="employee", allowed_permissions=["orders"])
    try:
        await bus_publish("order_status_changed",
                          {"order_id": "after-revoke-1", "amount_from": 202,
                           "from_code": "USD", "to_code": "CUP"},
                          roles=("admin", "employee"))
        pending = await _drain(sub)
        assert len(pending) == 1 and pending[0]["staff"] is True
        # El permiso se retira (revalidación en caliente) ANTES de entregar.
        update_authz(sub, "employee", [], [])
        # Compuerta final: el frame pendiente NO puede salir.
        assert reauthorize_event(sub, pending[0]) is False
    finally:
        await bus_unsubscribe(sub)


@pytest.mark.asyncio
async def test_staff06r2_two_pending_events_both_dropped():
    # R02 — dos eventos encolados bajo el snapshot viejo; tras el refresco a []
    # NINGUNO debe entregarse (modela frames en ambas colas).
    sub = await bus_subscribe("s06r2_b", role="employee", allowed_permissions=["orders"])
    try:
        for i in (1, 2):
            await bus_publish("order_status_changed",
                              {"order_id": f"after-revoke-{i}", "amount_from": 200 + i},
                              roles=("admin", "employee"))
        pending = await _drain(sub)
        assert len(pending) == 2
        update_authz(sub, "employee", [], [])
        assert all(reauthorize_event(sub, ev) is False for ev in pending)
    finally:
        await bus_unsubscribe(sub)


@pytest.mark.asyncio
async def test_staff06r2_personal_event_survives_revocation():
    # Feed PERSONAL del dueño (user_id=...) no se re-chequea por capacidad: debe
    # entregarse aunque el usuario no tenga permisos de staff.
    sub = await bus_subscribe("s06r2_owner", role="normal")
    try:
        await bus_publish("order_status_changed",
                          {"order_id": "mine", "from_code": "USD", "to_code": "CUP"},
                          user_id="s06r2_owner")
        pending = await _drain(sub)
        assert len(pending) == 1 and pending[0]["staff"] is False
        update_authz(sub, "normal", [], [])
        assert reauthorize_event(sub, pending[0]) is True
    finally:
        await bus_unsubscribe(sub)


@pytest.mark.asyncio
async def test_staff06r2_still_authorized_event_passes_gate():
    # Si el permiso se conserva, el evento pendiente SÍ sale.
    sub = await bus_subscribe("s06r2_keep", role="employee", allowed_permissions=["orders"])
    try:
        await bus_publish("order_created", {"id": "x", "from_code": "USD", "to_code": "CUP"},
                          roles=("admin", "employee"))
        pending = await _drain(sub)
        assert reauthorize_event(sub, pending[0]) is True  # sigue con 'orders'
        # Y al acotar la moneda fuera de ámbito, se descarta en la compuerta.
        update_authz(sub, "employee", ["orders"], ["EUR"])
        assert reauthorize_event(sub, pending[0]) is False
    finally:
        await bus_unsubscribe(sub)


@pytest.mark.asyncio
async def test_staff06r2_admin_pending_event_always_passes():
    sub = await bus_subscribe("s06r2_admin", role="admin")
    try:
        await bus_publish("order_created", {"id": "x"}, roles=("admin", "employee"))
        pending = await _drain(sub)
        update_authz(sub, "admin", [], [])  # admin sigue viendo todo
        assert reauthorize_event(sub, pending[0]) is True
    finally:
        await bus_unsubscribe(sub)


# ------------------------------------------------------------------
# pickups_changed — antes broadcast-a-todos; ahora feed de staff gated por
# 'products' (lo consume SOLO el panel Inventario→Tiendas). Un cliente ya NO
# lo recibe; un empleado SIN 'products' tampoco; con 'products' sí; admin sí.
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pickups_changed_gated_to_products_capability():
    s_admin = await bus_subscribe("s06r_pk_admin", role="admin")
    s_prod = await bus_subscribe("s06r_pk_prod", role="employee",
                                 allowed_permissions=["products"])
    s_noprod = await bus_subscribe("s06r_pk_noprod", role="employee",
                                   allowed_permissions=["orders", "withdrawals"])
    s_client = await bus_subscribe("s06r_pk_client", role="normal")
    try:
        await bus_publish("pickups_changed", {"redemption_id": "r1"},
                          roles=("admin", "employee"))
        assert await _got(s_admin) is True        # admin ve el panel
        assert await _got(s_prod) is True          # empleado CON 'products'
        assert await _got(s_noprod) is False       # empleado SIN 'products' → NO
        assert await _got(s_client) is False       # cliente ya NO lo recibe
    finally:
        for s in (s_admin, s_prod, s_noprod, s_client):
            await bus_unsubscribe(s)


# ------------------------------------------------------------------
# STAFF-06-O01 — el permiso EFECTIVO del publicador (`require_perm`) viaja hasta
# la ENTREGA FINAL. Antes `_push` no lo sellaba y `reauthorize_event` volvía al
# predeterminado del tipo (`_STAFF_EVENT_CAP`), por lo que la compuerta de salida
# podía comprobar una capacidad DISTINTA de la que eligió el emisor. Ahora el
# sobre lleva `require_perm` y la compuerta reautoriza contra EXACTAMENTE esa.
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_staff06o01_override_revocation_respected_at_delivery():
    # O01a — se retira el permiso del OVERRIDE ('kyc') pero se conserva el
    # predeterminado del tipo ('transactions'). El evento pendiente NO debe
    # salir: la compuerta reautoriza contra 'kyc', no contra 'transactions'.
    sub = await bus_subscribe("s06o01_a", role="employee",
                              allowed_permissions=["kyc", "transactions"])
    try:
        await bus_publish("ledger_changed", {"reason": "sensitive"},
                          roles=("admin", "employee"), require_perm="kyc")
        pending = await _drain(sub)
        assert len(pending) == 1 and pending[0]["staff"] is True
        assert pending[0]["require_perm"] == "kyc"   # sellado en el sobre
        update_authz(sub, "employee", ["transactions"], [])  # quita kyc, deja tx
        assert reauthorize_event(sub, pending[0]) is False
    finally:
        await bus_unsubscribe(sub)


@pytest.mark.asyncio
async def test_staff06o01_override_authorized_event_not_dropped():
    # O01b — aviso legítimo: el empleado conserva 'kyc' (permiso del publicador)
    # y NO tiene 'transactions'. La compuerta debe ENTREGARLO comprobando 'kyc',
    # no el predeterminado 'transactions' (que descartaría el evento por error).
    sub = await bus_subscribe("s06o01_b", role="employee",
                              allowed_permissions=["kyc"])
    try:
        await bus_publish("ledger_changed", {"reason": "sensitive"},
                          roles=("admin", "employee"), require_perm="kyc")
        pending = await _drain(sub)
        assert len(pending) == 1
        assert pending[0]["require_perm"] == "kyc"
        assert reauthorize_event(sub, pending[0]) is True   # conserva 'kyc'
    finally:
        await bus_unsubscribe(sub)


@pytest.mark.asyncio
async def test_staff06o01_override_survives_full_generator():
    # El sobre con `require_perm` sobrevive al generador completo
    # (event_iterator), igual que routes/live.py lo lleva a heartbeat_queue, y
    # se reautoriza al salir: autorizado mientras conserve 'kyc', denegado al
    # retirarlo.
    sub = await bus_subscribe("s06o01_gen", role="employee",
                              allowed_permissions=["kyc", "transactions"])
    try:
        await bus_publish("ledger_changed", {"reason": "sensitive"},
                          roles=("admin", "employee"), require_perm="kyc")
        gen = event_iterator(sub)
        ev = await asyncio.wait_for(gen.__anext__(), 0.2)
        assert ev["require_perm"] == "kyc"
        assert reauthorize_event(sub, ev) is True
        update_authz(sub, "employee", ["transactions"], [])
        assert reauthorize_event(sub, ev) is False
        await gen.aclose()
    finally:
        await bus_unsubscribe(sub)


@pytest.mark.asyncio
async def test_staff06o01_personal_same_name_event_not_gated_by_override():
    # Evento PERSONAL con el MISMO nombre que un feed operativo con override:
    # no se re-chequea por capacidad y se entrega al dueño; `require_perm` del
    # sobre es None para feeds personales.
    owner = await bus_subscribe("s06o01_owner", role="normal")
    try:
        await bus_publish("ledger_changed", {"reason": "your balance"},
                          user_id="s06o01_owner")
        pending = await _drain(owner)
        assert len(pending) == 1 and pending[0]["staff"] is False
        assert pending[0].get("require_perm") is None
        assert reauthorize_event(owner, pending[0]) is True
    finally:
        await bus_unsubscribe(owner)
