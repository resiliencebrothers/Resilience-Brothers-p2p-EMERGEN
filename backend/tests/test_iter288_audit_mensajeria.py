"""iter288 — Auditoría de mensajería eeed556: MSG01–MSG11.

MSG01 · Un avance de estado atrasado (cancelación/reasignación en medio)
pierde con 409 y no revive ni altera la entrega.
MSG02 · Un solo trabajo activo por (kind, ref_id): índice único active_key.
MSG03 · Operación de origen rechazada → sin creación/aceptación nuevas; el
rechazo del depósito cancela su recogida o deja incidencia si ya se ejecutó.
MSG04 · Tarea durable delivery_sync_pending: tras un corte, el healer crea o
actualiza exactamente un reparto con la tarifa vigente, sin re-cobrar.
MSG05 · Una tarifa atrasada jamás reescribe un pago confirmado: queda como
ajuste pendiente trazable; la confirmación congela el importe liquidado.
MSG06 · El rechazo de reserva exige que la reserva leída siga vigente.
MSG07 · Ganancias/conteos por agregación (no ventana de 50); reservas
dirigidas siempre visibles.
MSG08 · Reasignar limpia la ubicación GPS del mensajero anterior.
MSG11 · NaN/Infinity rechazados en tarifas municipales y km.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, with_totp_admin

API = f"{BASE_URL}/api"
MARK = "IT288"
COURIER_A = "it288_courier_a"
COURIER_B = "it288_courier_b"
CLIENT_ID = "it288_client"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _run(async_fn):
    from db_client import client as _motor_client
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        _motor_client._io_loop = None
        return loop.run_until_complete(async_fn())
    finally:
        _motor_client._io_loop = None
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _mk_user(uid, is_courier=False):
    _db().users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "email": f"{uid}@it288.test", "name": f"{MARK} {uid}",
        "role": "vip", "account_status": "active", "is_verified": True,
        "is_courier": is_courier, "vip_balances": {}}}, upsert=True)


def _fake_user(uid):
    return {"user_id": uid, "name": f"{MARK} {uid}", "role": "vip",
            "is_courier": True, "account_status": "active",
            "email": f"{uid}@it288.test"}


def _plant_delivery(status="available", courier_id=None, kind="redemption",
                    ref_id=None, fee=10.0, assigned_to=None, extra=None):
    did = f"it288_d_{uuid.uuid4().hex[:10]}"
    rid = ref_id or f"it288_ref_{uuid.uuid4().hex[:10]}"
    now = _iso()
    doc = {
        "id": did, "kind": kind, "ref_id": rid,
        "active_key": f"{kind}:{rid}",
        "user_id": CLIENT_ID, "client_name": f"{MARK} client",
        "address": f"{MARK} address", "province": None,
        "amount_label": f"{MARK} shipment",
        "delivery_latitude": None, "delivery_longitude": None,
        "km": 20.0, "fee_usdt": float(fee), "share_pct_snapshot": 80.0,
        "courier_share_usdt": round(fee * 0.8, 2),
        "platform_share_usdt": round(fee * 0.2, 2),
        "status": status, "courier_id": courier_id,
        "courier_name": f"{MARK} courier" if courier_id else None,
        "assigned_to_courier_id": assigned_to,
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None, "created_at": now, "updated_at": now,
        "timeline": [{"status": "available", "at": now, "by": None}],
    }
    doc.update(extra or {})
    _db().deliveries.insert_one(doc)
    return did, rid


def _plant_redemption(rid, status="pending", fee=10.0):
    _db().redemptions.update_one({"id": rid}, {"$set": {
        "id": rid, "user_id": CLIENT_ID, "user_name": f"{MARK} client",
        "status": status, "total_usd": 40, "settlement_currency": "USDT",
        "courier_fee_usdt": float(fee), "courier_fee_usd": float(fee),
        "courier_km": 20, "product_name": f"{MARK} product", "quantity": 1,
        "delivery_address": f"{MARK} address"}}, upsert=True)


def _cleanup():
    db = _db()
    db.deliveries.delete_many({"id": {"$regex": "^it288_"}})
    db.deliveries.delete_many({"ref_id": {"$regex": "^it288_"}})
    db.deliveries.delete_many({"courier_id": {"$in": [COURIER_A, COURIER_B]}})
    db.redemptions.delete_many({"id": {"$regex": "^it288_"}})
    db.deposits.delete_many({"id": {"$regex": "^it288_"}})
    db.courier_municipality_rates.delete_many({"municipality": {"$regex": MARK}})
    db.users.delete_many({"user_id": {"$regex": "^it288_"}})
    db.notifications.delete_many({"title": {"$regex": MARK}})


def setup_module(module):
    _cleanup()
    _mk_user(COURIER_A, is_courier=True)
    _mk_user(COURIER_B, is_courier=True)
    _mk_user(CLIENT_ID)


def teardown_module(module):
    _cleanup()


# ============================================================
# MSG01 — avance de estado atrasado pierde con conflicto
# ============================================================

def _stale_progress(did, uid, new_status, inject):
    """Ejecuta courier_update_status inyectando `inject` (pymongo, sync)
    entre la lectura y la escritura — el punto exacto de la carrera."""
    async def _f():
        import routes.deliveries as dr
        orig_iso, orig_ru = dr.iso, dr.require_user

        async def fake_ru(request):
            return _fake_user(uid)

        fired = {"done": False}

        def hooked_iso(x):
            if not fired["done"]:
                fired["done"] = True
                inject()
            return orig_iso(x)

        dr.require_user, dr.iso = fake_ru, hooked_iso
        try:
            try:
                await dr.courier_update_status(did, {"status": new_status}, None)
                return 200
            except dr.HTTPException as ex:
                return ex.status_code
        finally:
            dr.iso, dr.require_user = orig_iso, orig_ru
    return _run(_f)


def test_msg01_stale_delivered_cannot_revive_cancelled():
    did, _ = _plant_delivery(status="arrived", courier_id=COURIER_A)

    def cancel_mid_flight():
        _db().deliveries.update_one(
            {"id": did}, {"$set": {"status": "cancelled"},
                          "$unset": {"active_key": ""}})

    code = _stale_progress(did, COURIER_A, "delivered", cancel_mid_flight)
    assert code == 409
    d = _db().deliveries.find_one({"id": did})
    assert d["status"] == "cancelled"
    assert not d.get("payout_credited")
    # No se registró la transición perdida en la línea de tiempo.
    assert not any(e.get("status") == "delivered" for e in d["timeline"])


def test_msg01_stale_start_cannot_override_reassignment():
    did, _ = _plant_delivery(status="accepted", courier_id=COURIER_A)

    def reassign_mid_flight():
        _db().deliveries.update_one({"id": did}, {"$set": {
            "status": "available", "courier_id": None, "courier_name": None,
            "assigned_to_courier_id": COURIER_B}})

    code = _stale_progress(did, COURIER_A, "on_the_way", reassign_mid_flight)
    assert code == 409
    d = _db().deliveries.find_one({"id": did})
    assert d["status"] == "available"
    assert d["assigned_to_courier_id"] == COURIER_B


# ============================================================
# MSG02 — un solo trabajo activo por operación
# ============================================================

def test_msg02_unique_active_key_blocks_duplicates():
    _, rid = _plant_delivery(status="available")
    dup = {"id": f"it288_d_{uuid.uuid4().hex[:10]}", "kind": "redemption",
           "ref_id": rid, "active_key": f"redemption:{rid}",
           "status": "available"}
    try:
        _db().deliveries.insert_one(dup)
        raise AssertionError("el índice único active_key no bloqueó el duplicado")
    except DuplicateKeyError:
        pass


def test_msg02_ensure_delivery_job_is_idempotent():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid)
    ref = _db().redemptions.find_one({"id": rid}, {"_id": 0})

    async def _f():
        from services.deliveries import ensure_delivery_job
        a = await ensure_delivery_job("redemption", ref, km=20, fee_usdt=10)
        b = await ensure_delivery_job("redemption", ref, km=20, fee_usdt=10)
        return a["id"], b["id"]
    id_a, id_b = _run(_f)
    assert id_a == id_b
    assert _db().deliveries.count_documents(
        {"kind": "redemption", "ref_id": rid,
         "status": {"$ne": "cancelled"}}) == 1
    # Tras cancelar, una reexpedición legítima sigue siendo posible.
    _run(_ensure_cancel(rid))
    async def _g():
        from services.deliveries import ensure_delivery_job
        return await ensure_delivery_job("redemption", ref, km=20, fee_usdt=10)
    redo = _run(_g)
    assert redo["id"] != id_a


def _ensure_cancel(rid):
    async def _f():
        from services.deliveries import cancel_active_delivery
        await cancel_active_delivery("redemption", rid, note="test")
    return _f


def test_msg02_api_second_manual_create_conflicts():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid)
    r1 = requests.post(f"{API}/admin/deliveries", headers=_hdr(),
                       json={"kind": "redemption", "ref_id": rid}, timeout=15)
    assert r1.status_code == 200, r1.text
    r2 = requests.post(f"{API}/admin/deliveries", headers=_hdr(),
                       json={"kind": "redemption", "ref_id": rid}, timeout=15)
    assert r2.status_code == 409, r2.text


# ============================================================
# MSG03 — origen rechazado cierra todas las vías
# ============================================================

def test_msg03_cannot_create_delivery_for_rejected_redemption():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid, status="rejected")
    r = requests.post(f"{API}/admin/deliveries", headers=_hdr(),
                      json={"kind": "redemption", "ref_id": rid}, timeout=15)
    assert r.status_code == 409, r.text


def test_msg03_claim_of_rejected_origin_is_blocked_and_cancelled():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid, status="rejected")
    did, _ = _plant_delivery(status="available", ref_id=rid)

    async def _f():
        import routes.deliveries as dr
        orig_ru = dr.require_user

        async def fake_ru(request):
            return _fake_user(COURIER_A)
        dr.require_user = fake_ru
        try:
            try:
                await dr.claim_delivery(did, None)
                return 200
            except dr.HTTPException as ex:
                return ex.status_code
        finally:
            dr.require_user = orig_ru
    code = _run(_f)
    assert code == 409
    d = _db().deliveries.find_one({"id": did})
    assert d["status"] == "cancelled"


def _plant_deposit(dep_id, status="pending"):
    _db().deposits.update_one({"id": dep_id}, {"$set": {
        "id": dep_id, "user_id": CLIENT_ID, "currency": "USD",
        "amount": 1500, "usdt_equivalent": 1500, "status": status,
        "method": "cash", "cash_mode": "courier",
        "pickup_address": f"{MARK} pickup", "pickup_phone": "000",
        "contact_name": f"{MARK} sender", "created_at": _iso()}},
        upsert=True)


def test_msg03_deposit_reject_cancels_pending_pickup():
    dep_id = f"it288_dep_{uuid.uuid4().hex[:10]}"
    _plant_deposit(dep_id)
    did, _ = _plant_delivery(status="available", kind="deposit",
                             ref_id=dep_id, fee=0)
    r = requests.post(f"{API}/admin/deposits/{dep_id}/reject", headers=_hdr(),
                      json={"admin_note": f"{MARK} rechazo"}, timeout=15)
    assert r.status_code == 200, r.text
    d = _db().deliveries.find_one({"id": did})
    assert d["status"] == "cancelled"


def test_msg03_deposit_reject_with_executed_pickup_leaves_incident():
    dep_id = f"it288_dep_{uuid.uuid4().hex[:10]}"
    _plant_deposit(dep_id)
    did, _ = _plant_delivery(status="delivered", courier_id=COURIER_A,
                             kind="deposit", ref_id=dep_id, fee=0)
    r = requests.post(f"{API}/admin/deposits/{dep_id}/reject", headers=_hdr(),
                      json={"admin_note": f"{MARK} rechazo"}, timeout=15)
    assert r.status_code == 200, r.text
    d = _db().deliveries.find_one({"id": did})
    # El movimiento físico NO se oculta: incidencia visible, sin cancelar.
    assert d["status"] == "delivered"
    assert d.get("origin_conflict"), "falta la incidencia origin_conflict"


# ============================================================
# MSG04 — recuperación cobro↔reparto tras interrupciones
# ============================================================

def _heal_sync():
    async def _f():
        from services.deliveries import heal_delivery_sync
        return await heal_delivery_sync(_iso(0))
    return _run(_f)


def test_msg04_heal_creates_missing_job_exactly_once():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid, fee=10)
    # Estado del auditor: cobro completado, proceso muerto ANTES de crear el
    # trabajo — la tarea durable quedó publicada junto con el cobro.
    _db().redemptions.update_one({"id": rid}, {"$set": {
        "delivery_sync_pending": {"op_id": f"it288op_{rid}",
                                  "at": _iso(minutes_ago=10)}}})
    _heal_sync()
    jobs = list(_db().deliveries.find(
        {"kind": "redemption", "ref_id": rid, "status": {"$ne": "cancelled"}}))
    assert len(jobs) == 1
    assert jobs[0]["fee_usdt"] == 10
    assert not (_db().redemptions.find_one({"id": rid}) or {}).get(
        "delivery_sync_pending")
    # Idempotente: otra pasada no duplica ni cobra nada.
    _heal_sync()
    assert _db().deliveries.count_documents(
        {"kind": "redemption", "ref_id": rid,
         "status": {"$ne": "cancelled"}}) == 1


def test_msg04_heal_updates_stale_job_to_current_fee():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid, fee=20)  # la tarifa de origen ya subió a 20
    did, _ = _plant_delivery(status="available", ref_id=rid, fee=10)
    _db().redemptions.update_one({"id": rid}, {"$set": {
        "delivery_sync_pending": {"op_id": f"it288op_{rid}",
                                  "at": _iso(minutes_ago=10)}}})
    _heal_sync()
    d = _db().deliveries.find_one({"id": did})
    assert d["fee_usdt"] == 20
    assert d["courier_share_usdt"] == 16


def test_msg04_api_fee_charge_leaves_no_pending_and_one_job():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid, fee=0)
    _db().redemptions.update_one(
        {"id": rid}, {"$set": {"courier_fee_usdt": 0, "courier_fee_usd": 0,
                               "courier_km": 0}})
    _db().users.update_one({"user_id": CLIENT_ID},
                           {"$set": {"vip_balances.USDT": 100.0}})
    r = requests.post(f"{API}/admin/redemptions/{rid}/courier-fee",
                      headers=_hdr(), json=with_totp_admin({"km": 20}),
                      timeout=20)
    assert r.status_code == 200, r.text
    doc = _db().redemptions.find_one({"id": rid})
    assert not doc.get("delivery_sync_pending")
    jobs = list(_db().deliveries.find(
        {"kind": "redemption", "ref_id": rid, "status": {"$ne": "cancelled"}}))
    assert len(jobs) == 1
    assert jobs[0]["fee_usdt"] == doc["courier_fee_usdt"]


# ============================================================
# MSG05 — la tarifa jamás reescribe un pago confirmado
# ============================================================

def test_msg05_late_fee_sync_never_rewrites_confirmed_payout():
    rid = f"it288_ref_{uuid.uuid4().hex[:10]}"
    _plant_redemption(rid, fee=20)
    did, _ = _plant_delivery(status="delivered", courier_id=COURIER_A,
                             ref_id=rid, fee=10)
    ref = _db().redemptions.find_one({"id": rid}, {"_id": 0})

    async def _f():
        import services.deliveries as sd
        orig_iso = sd.iso
        fired = {"done": False}

        def hooked_iso(x):
            if not fired["done"]:
                fired["done"] = True
                # La administración confirma y paga 8 ENTRE la lectura y la
                # sincronización de la tarifa nueva (10 → 20).
                _db().deliveries.update_one({"id": did}, {"$set": {
                    "status": "confirmed", "payout_credited": True,
                    "courier_share_paid_usdt": 8.0}})
            return orig_iso(x)
        sd.iso = hooked_iso
        try:
            await sd.upsert_delivery_for_charge("redemption", ref, km=40,
                                                fee_usdt=20)
        finally:
            sd.iso = orig_iso
    _run(_f)
    d = _db().deliveries.find_one({"id": did})
    # El historial de pago queda congelado (8 de una tarifa de 10)…
    assert d["courier_share_usdt"] == 8.0
    assert d["fee_usdt"] == 10.0
    assert d["courier_share_paid_usdt"] == 8.0
    # …y la diferencia queda como ajuste pendiente trazable, una sola vez.
    adj = d.get("fee_adjustment_pending")
    assert adj and adj["fee_usdt"] == 20.0 and adj["courier_share_usdt"] == 16.0
    assert sum(1 for e in d["timeline"]
               if e.get("status") == "fee_conflict") == 1


def test_msg05_confirm_freezes_the_amount_it_settles():
    did, _ = _plant_delivery(status="delivered", courier_id=COURIER_A, fee=10)
    d_stale = _db().deliveries.find_one({"id": did}, {"_id": 0})
    # La tarifa sube (8 → 16) DESPUÉS de la lectura del confirmador.
    _db().deliveries.update_one(
        {"id": did}, {"$set": {"fee_usdt": 20.0, "courier_share_usdt": 16.0}})

    async def _f():
        from services.deliveries import do_confirm_delivery
        from fastapi import HTTPException
        try:
            await do_confirm_delivery(
                d_stale, {"user_id": "it288_admin", "name": f"{MARK} admin",
                          "email": "a@it288.test", "role": "admin"})
            return 200
        except HTTPException as ex:
            return ex.status_code
    code = _run(_f)
    assert code == 409
    d = _db().deliveries.find_one({"id": did})
    assert not d.get("payout_credited")
    assert d["status"] == "delivered"


# ============================================================
# MSG06 — rechazo de reserva con reserva vigente
# ============================================================

def test_msg06_stale_rejection_keeps_new_reservation():
    did, _ = _plant_delivery(status="available", assigned_to=COURIER_A)

    async def _f():
        import routes.deliveries as dr
        orig_iso, orig_ru = dr.iso, dr.require_user

        async def fake_ru(request):
            return _fake_user(COURIER_A)

        fired = {"done": False}

        def hooked_iso(x):
            if not fired["done"]:
                fired["done"] = True
                # El admin reasigna la reserva a B entre lectura y escritura.
                _db().deliveries.update_one(
                    {"id": did},
                    {"$set": {"assigned_to_courier_id": COURIER_B}})
            return orig_iso(x)
        dr.require_user, dr.iso = fake_ru, hooked_iso
        try:
            try:
                await dr.reject_reservation(
                    did, {"reason": f"{MARK} no disponible"}, None)
                return 200
            except dr.HTTPException as ex:
                return ex.status_code
        finally:
            dr.iso, dr.require_user = orig_iso, orig_ru
    code = _run(_f)
    assert code == 409
    d = _db().deliveries.find_one({"id": did})
    assert d["assigned_to_courier_id"] == COURIER_B


# ============================================================
# MSG07 — totales completos y reservas siempre visibles
# ============================================================

def _vip_uid():
    s = _db().user_sessions.find_one({"session_token": VIP_TOKEN})
    assert s, "sesión VIP de pruebas no sembrada"
    return s["user_id"]


def test_msg07_earnings_are_aggregated_not_windowed():
    uid = _vip_uid()
    _db().users.update_one({"user_id": uid}, {"$set": {"is_courier": True}})
    base = requests.get(f"{API}/courier/deliveries", headers=_hdr(VIP_TOKEN),
                        timeout=15).json()["earnings"]
    docs = []
    now = datetime.now(timezone.utc)
    for i in range(51):
        at = (now - timedelta(hours=2) + timedelta(seconds=i)).isoformat()
        rid = f"it288_e_{uuid.uuid4().hex[:8]}"
        docs.append({"id": f"it288_d_{uuid.uuid4().hex[:10]}",
                     "kind": "redemption", "ref_id": rid,
                     "active_key": f"redemption:{rid}",
                     "status": "confirmed", "courier_id": uid,
                     "courier_share_usdt": 8.0, "fee_usdt": 10.0,
                     "payout_credited": True, "client_name": f"{MARK}",
                     "amount_label": f"{MARK}", "created_at": at,
                     "updated_at": at, "timeline": []})
    _db().deliveries.insert_many(docs)
    try:
        after = requests.get(f"{API}/courier/deliveries",
                             headers=_hdr(VIP_TOKEN), timeout=15).json()["earnings"]
        assert round(after["confirmed_usdt"] - base["confirmed_usdt"], 2) == 408.0
        assert after["completed_count"] - base["completed_count"] == 51
    finally:
        _db().deliveries.delete_many({"id": {"$in": [d["id"] for d in docs]}})


def test_msg07_old_reservation_survives_50_newer_open_jobs():
    uid = _vip_uid()
    _db().users.update_one({"user_id": uid}, {"$set": {"is_courier": True}})
    now = datetime.now(timezone.utc)
    reserved_id, _ = _plant_delivery(
        status="available", assigned_to=uid,
        extra={"created_at": (now - timedelta(days=2)).isoformat()})
    open_ids = []
    for i in range(50):
        did, _ = _plant_delivery(
            status="available",
            extra={"created_at": (now - timedelta(minutes=50 - i)).isoformat()})
        open_ids.append(did)
    try:
        data = requests.get(f"{API}/courier/deliveries",
                            headers=_hdr(VIP_TOKEN), timeout=15).json()
        mine_reserved = [d for d in data["available"]
                         if d["id"] == reserved_id]
        assert mine_reserved and mine_reserved[0]["reserved_for_me"] is True
    finally:
        _db().deliveries.delete_many(
            {"id": {"$in": open_ids + [reserved_id]}})


# ============================================================
# MSG08 — reasignar limpia la ubicación del mensajero anterior
# ============================================================

def test_msg08_reassign_clears_previous_courier_location():
    did, _ = _plant_delivery(
        status="accepted", courier_id=COURIER_A,
        extra={"courier_location": {"lat": 23.1, "lon": -82.3,
                                    "updated_at": _iso()}})
    r = requests.post(f"{API}/admin/deliveries/{did}/assign", headers=_hdr(),
                      json={"courier_id": COURIER_B}, timeout=15)
    assert r.status_code == 200, r.text
    d = _db().deliveries.find_one({"id": did})
    assert "courier_location" not in d
    assert d["assigned_to_courier_id"] == COURIER_B


# ============================================================
# MSG11 — validación numérica estricta
# ============================================================

def test_msg11_municipality_rate_rejects_nonfinite_prices():
    db = _db()
    mid = f"muni_it288_{uuid.uuid4().hex[:8]}"
    db.courier_municipality_rates.insert_one(
        {"id": mid, "municipality": f"{MARK} Zona", "price_usdt": 3.0,
         "aliases": [], "active": True})
    try:
        for bad in ("NaN", "Infinity", "-Infinity", "nan"):
            r = requests.put(
                f"{API}/admin/courier/municipality-rates/{mid}",
                headers=_hdr(), json={"price_usdt": bad}, timeout=15)
            assert r.status_code == 400, f"{bad}: {r.status_code} {r.text}"
        row = db.courier_municipality_rates.find_one({"id": mid})
        assert row["price_usdt"] == 3.0  # sin cambios en la base
        ok = requests.put(f"{API}/admin/courier/municipality-rates/{mid}",
                          headers=_hdr(), json={"price_usdt": 4.5}, timeout=15)
        assert ok.status_code == 200 and ok.json()["price_usdt"] == 4.5
    finally:
        db.courier_municipality_rates.delete_many({"id": mid})


def test_msg11_km_rejects_nonfinite():
    from fastapi import HTTPException
    from services.courier_fee import parse_km_payload
    for bad in ("NaN", "Infinity", float("nan"), float("inf")):
        try:
            parse_km_payload({"km": bad})
            raise AssertionError(f"km={bad} fue aceptado")
        except HTTPException as ex:
            assert ex.status_code == 400
    assert parse_km_payload({"km": 12.5}) == 12.5
