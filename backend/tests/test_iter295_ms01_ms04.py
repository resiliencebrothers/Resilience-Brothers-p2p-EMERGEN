"""iter295 — Revisión de mensajería 56054ab: MS01–MS04.

MS01 · Los ajustes de comisión NO se pierden tras confirmar ni al cambiar la
tarifa varias veces: un cambio posterior a la confirmación deja (o actualiza
al último objetivo por revisión) un ajuste pendiente recuperable; un
ejecutor atrasado no puede dejar el ajuste con una revisión anterior; si la
tarifa vuelve al importe ya pagado, el ajuste obsoleto se retira.
MS02 · Una creación atrasada de reparto NO sobrevive a la anulación (ni a
una tarifa más nueva) de su origen: verificación post-inserción (principio
de bandera) — se relee el origen DESPUÉS de insertar y se converge.
MS03 · La cancelación por rechazo JAMÁS sobrescribe una recogida ya sellada:
el filtro decide en el update ('delivered' excluido) y el manejador relee y
deja la incidencia si la recogida ganó la carrera.
MS04 · Las métricas operativas agregan TODOS los documentos del filtro
(2.001 de 2.001), sin el tope de 2.000.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
MARK = "IT295"
COURIER_A = "it295_courier_a"
CLIENT_ID = "it295_client"


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
        "user_id": uid, "email": f"{uid}@it295.test", "name": f"{MARK} {uid}",
        "role": "vip", "account_status": "active", "is_verified": True,
        "is_courier": is_courier, "vip_balances": {}}}, upsert=True)


def _plant_delivery(status="available", courier_id=None, kind="redemption",
                    ref_id=None, fee=10.0, extra=None):
    did = f"it295_d_{uuid.uuid4().hex[:10]}"
    rid = ref_id or f"it295_ref_{uuid.uuid4().hex[:10]}"
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
        "assigned_to_courier_id": None,
        "payout_credited": False, "payout_credited_at": None,
        "created_by": None, "created_at": now, "updated_at": now,
        "timeline": [{"status": "available", "at": now, "by": None}],
    }
    if status == "cancelled":
        doc.pop("active_key")
    doc.update(extra or {})
    _db().deliveries.insert_one(doc)
    return did, rid


def _plant_redemption(rid, status="pending", fee=10.0, rev=0):
    _db().redemptions.update_one({"id": rid}, {"$set": {
        "id": rid, "user_id": CLIENT_ID, "user_name": f"{MARK} client",
        "status": status, "total_usd": 40, "settlement_currency": "USDT",
        "courier_fee_usdt": float(fee), "courier_fee_usd": float(fee),
        "courier_fee_rev": int(rev),
        "courier_km": 20, "product_name": f"{MARK} product", "quantity": 1,
        "delivery_address": f"{MARK} address"}}, upsert=True)


def _plant_deposit(status="pending", amount=1500.0, extra=None):
    dep_id = f"it295_dep_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": dep_id, "user_id": CLIENT_ID, "user_name": f"{MARK} client",
        "amount": float(amount), "currency": "USD", "method": "cash_courier",
        "status": status, "contact_name": f"{MARK} contact",
        "pickup_address": f"{MARK} addr", "pickup_phone": "+53 555",
        "created_at": _iso(), "updated_at": _iso(),
    }
    doc.update(extra or {})
    _db().deposits.insert_one(doc)
    return dep_id


def _cleanup():
    db = _db()
    db.deliveries.delete_many({"id": {"$regex": "^it295_"}})
    db.deliveries.delete_many({"ref_id": {"$regex": "^it295_"}})
    db.redemptions.delete_many({"id": {"$regex": "^it295_"}})
    db.deposits.delete_many({"id": {"$regex": "^it295_"}})
    db.users.delete_many({"user_id": {"$regex": "^it295_"}})
    db.notifications.delete_many({"message": {"$regex": "it295_"}})
    db.notifications.delete_many({"title": {"$regex": MARK}})


def setup_module(module):
    _cleanup()
    _mk_user(COURIER_A, is_courier=True)
    _mk_user(CLIENT_ID)


def teardown_module(module):
    _cleanup()


def _simulate_payout_claim(did, share=8.0, fee=10.0):
    """Deja la entrega EXACTAMENTE como queda entre el claim del pago y el
    sello 'confirmed' de do_confirm_delivery."""
    _db().deliveries.update_one({"id": did}, {"$set": {
        "payout_credited": True, "payout_credited_at": _iso(),
        "courier_share_paid_usdt": float(share),
        "fee_paid_usdt": float(fee),
        "platform_share_paid_usdt": round(fee - share, 2)}})


def _upsert_charge(kind, ref_doc, fee, rev, km=20.0):
    async def _f():
        from services.deliveries import upsert_delivery_for_charge
        return await upsert_delivery_for_charge(
            kind, ref_doc, km=km, fee_usdt=fee, fee_rev=rev)
    return _run(_f)


# ============================================================
# MS01 — el ajuste sigue al ÚLTIMO objetivo y jamás desaparece
# ============================================================

class TestMS01AdjustmentsSurvive:
    def test_fee_change_after_confirmation_flags_adjustment(self):
        """Variante A: reparto CONFIRMADO y pagado (8 de tarifa 10); la
        tarifa cambia a 20 — el cobro al cliente ya ocurrió y la diferencia
        DEBE quedar como ajuste pendiente (antes desaparecía)."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1})
        _plant_redemption(rid, fee=20.0, rev=2)
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "confirmed", "el histórico no se reescribe"
        assert d["courier_share_paid_usdt"] == 8.0, "pago histórico intacto"
        assert d["fee_usdt"] == 10.0, "la tarifa congelada no cambia"
        adj = d.get("fee_adjustment_pending")
        assert adj, "el cambio posterior a confirmar NO puede desaparecer"
        assert adj["courier_share_usdt"] == 16.0
        assert adj["fee_usdt"] == 20.0
        # Reintento con la MISMA revisión: idempotente, un solo registro.
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        conflicts = [e for e in d["timeline"]
                     if e.get("status") == "fee_conflict"]
        assert len(conflicts) == 1

    def test_annulment_after_confirmation_flags_adjustment(self):
        """Variante A con km=0: la anulación posterior a confirmar reembolsa
        al cliente — el objetivo 0 queda como ajuste, no en silencio."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1})
        _plant_redemption(rid, fee=0.0, rev=2)
        _upsert_charge("redemption", {"id": rid}, fee=0.0, rev=2, km=0.0)
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "confirmed"
        adj = d.get("fee_adjustment_pending")
        assert adj and adj["courier_share_usdt"] == 0.0 \
            and adj["fee_usdt"] == 0.0

    def test_second_revision_updates_pending_adjustment(self):
        """Variante B: cambios 10→20→30 con el pago iniciado — el objetivo
        vigente debe ser 24 (80% de 30), no quedarse en 16; el histórico
        pagado sigue en 8."""
        did, rid = _plant_delivery(status="delivered", courier_id=COURIER_A,
                                   fee=10.0, extra={"fee_rev": 1})
        _plant_redemption(rid, fee=10.0, rev=1)
        _simulate_payout_claim(did, share=8.0, fee=10.0)
        _plant_redemption(rid, fee=20.0, rev=2)
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        _plant_redemption(rid, fee=30.0, rev=3)
        _upsert_charge("redemption", {"id": rid}, fee=30.0, rev=3)
        d = _db().deliveries.find_one({"id": did})
        adj = d.get("fee_adjustment_pending")
        assert adj and adj["courier_share_usdt"] == 24.0, \
            f"el ajuste debe seguir al último objetivo (24), no {adj}"
        assert adj["fee_usdt"] == 30.0 and adj["fee_rev"] == 3
        assert d["courier_share_paid_usdt"] == 8.0

    def test_stale_executor_cannot_downgrade_adjustment(self):
        did, rid = _plant_delivery(status="delivered", courier_id=COURIER_A,
                                   fee=10.0, extra={"fee_rev": 1})
        _plant_redemption(rid, fee=30.0, rev=3)
        _simulate_payout_claim(did, share=8.0, fee=10.0)
        _upsert_charge("redemption", {"id": rid}, fee=30.0, rev=3)
        # Ejecutor ATRASADO (leyó 20, rev 2) termina después: pierde.
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        adj = d.get("fee_adjustment_pending")
        assert adj and adj["courier_share_usdt"] == 24.0 \
            and adj["fee_rev"] == 3, \
            "una revisión anterior jamás degrada el ajuste vigente"

    def test_adjustment_cleared_when_fee_returns_to_paid(self):
        """Si una revisión más nueva devuelve la tarifa al importe ya
        liquidado, el ajuste obsoleto se retira: no queda nada que ajustar."""
        did, rid = _plant_delivery(status="delivered", courier_id=COURIER_A,
                                   fee=10.0, extra={"fee_rev": 1})
        _plant_redemption(rid, fee=20.0, rev=2)
        _simulate_payout_claim(did, share=8.0, fee=10.0)
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        assert _db().deliveries.find_one(
            {"id": did})["fee_adjustment_pending"]["courier_share_usdt"] == 16.0
        _plant_redemption(rid, fee=10.0, rev=3)
        _upsert_charge("redemption", {"id": rid}, fee=10.0, rev=3)
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("fee_adjustment_pending"), \
            "objetivo == pagado → el ajuste pendiente queda sin efecto"
        resolved = [e for e in d["timeline"]
                    if e.get("status") == "fee_conflict_resolved"]
        assert len(resolved) == 1

    def test_normal_flow_still_updates_without_adjustment(self):
        """Control: sin pago iniciado, el cambio de tarifa actualiza el
        reparto normalmente y NO deja ajustes."""
        did, rid = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                   fee=10.0, extra={"fee_rev": 1})
        _plant_redemption(rid, fee=20.0, rev=2)
        _upsert_charge("redemption", {"id": rid}, fee=20.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        assert d["fee_usdt"] == 20.0 and d["courier_share_usdt"] == 16.0
        assert not d.get("fee_adjustment_pending")


# ============================================================
# MS02 — la creación atrasada converge tras la anulación
# ============================================================

def _paused_insert_scenario(rid, stale_fee, stale_rev, concurrent):
    """Ejecuta la creación del reparto pausando ENTRE la lectura del activo
    y la inserción (la ventana exacta de MS02); durante la pausa corre
    `concurrent(sd, real_db)` y después se reanuda la inserción."""
    async def _f():
        import services.deliveries as sd
        real_db = sd.db
        hit, go = asyncio.Event(), asyncio.Event()
        state = {"paused": False}

        class _Deliveries:
            def __getattr__(self, n):
                return getattr(real_db.deliveries, n)

            async def insert_one(self, doc):
                if not state["paused"]:
                    state["paused"] = True
                    hit.set()
                    await go.wait()
                return await real_db.deliveries.insert_one(doc)

        class _DB:
            deliveries = _Deliveries()

            def __getattr__(self, n):
                return getattr(real_db, n)

            def __getitem__(self, n):
                return real_db[n]

        sd.db = _DB()
        try:
            ref = await real_db.redemptions.find_one({"id": rid}, {"_id": 0})
            task = asyncio.create_task(sd.upsert_delivery_for_charge(
                "redemption", ref, km=20.0, fee_usdt=stale_fee,
                fee_rev=stale_rev))
            await hit.wait()
            await concurrent(sd, real_db)
            go.set()
            return await task
        finally:
            sd.db = real_db
    return _run(_f)


class TestMS02StaleCreation:
    def test_stale_insert_converges_after_annulment(self):
        """Orden forzado «inicio de creación de 20 → anulación a 0 →
        inserción atrasada»: NO queda un reparto operable con tarifa 20."""
        rid = f"it295_ref_{uuid.uuid4().hex[:10]}"
        _plant_redemption(rid, fee=20.0, rev=1)

        async def _annul(sd, real_db):
            # La anulación reembolsa y sube la revisión EN el origen…
            await real_db.redemptions.update_one(
                {"id": rid}, {"$set": {"courier_fee_usdt": 0.0,
                                       "courier_fee_usd": 0.0,
                                       "courier_fee_rev": 2}})
            # …y su sincronización no ve ningún reparto todavía.
            res = await sd.upsert_delivery_for_charge(
                "redemption", {"id": rid}, km=0.0, fee_usdt=0.0, fee_rev=2)
            assert res is None

        _paused_insert_scenario(rid, stale_fee=20.0, stale_rev=1,
                                concurrent=_annul)
        rows = list(_db().deliveries.find({"ref_id": rid}))
        operable = [r for r in rows if r.get("status") != "cancelled"]
        assert not operable, \
            f"la publicación atrasada no puede quedar operable: {operable}"
        # El reparto insertado convergió a cancelado con la revisión nueva.
        assert rows and rows[0]["status"] == "cancelled"
        assert rows[0]["fee_rev"] == 2
        # Nadie puede aceptarlo ni cobrar los 16 USDT del cargo anulado.
        assert not rows[0].get("active_key")

    def test_stale_insert_converges_to_newer_positive_fee(self):
        """La misma ventana contra una tarifa MÁS NUEVA (30, rev 2): el
        resultado es UN solo reparto con la tarifa vigente."""
        rid = f"it295_ref_{uuid.uuid4().hex[:10]}"
        _plant_redemption(rid, fee=20.0, rev=1)

        async def _newer(sd, real_db):
            await real_db.redemptions.update_one(
                {"id": rid}, {"$set": {"courier_fee_usdt": 30.0,
                                       "courier_fee_usd": 30.0,
                                       "courier_fee_rev": 2}})
            ref = await real_db.redemptions.find_one({"id": rid}, {"_id": 0})
            fresh = await sd.upsert_delivery_for_charge(
                "redemption", ref, km=20.0, fee_usdt=30.0, fee_rev=2)
            assert fresh and fresh["fee_usdt"] == 30.0

        _paused_insert_scenario(rid, stale_fee=20.0, stale_rev=1,
                                concurrent=_newer)
        rows = list(_db().deliveries.find({"ref_id": rid,
                                           "status": {"$ne": "cancelled"}}))
        assert len(rows) == 1, "exactamente un reparto operable"
        assert rows[0]["fee_usdt"] == 30.0 and rows[0]["fee_rev"] == 2

    def test_stale_insert_converges_after_origin_rejected(self):
        """La ventana contra un RECHAZO del origen: el reparto atrasado no
        queda operable."""
        rid = f"it295_ref_{uuid.uuid4().hex[:10]}"
        _plant_redemption(rid, fee=20.0, rev=1)

        async def _reject(sd, real_db):
            await real_db.redemptions.update_one(
                {"id": rid}, {"$set": {"status": "rejected"}})

        _paused_insert_scenario(rid, stale_fee=20.0, stale_rev=1,
                                concurrent=_reject)
        rows = list(_db().deliveries.find({"ref_id": rid}))
        operable = [r for r in rows if r.get("status") != "cancelled"]
        assert not operable, "el origen rechazado no publica repartos"


# ============================================================
# MS03 — la recogida sellada JAMÁS es sobrescrita por el rechazo
# ============================================================

class TestMS03SealedPickupWins:
    def test_seal_between_read_and_cancel_leaves_incident(self):
        """Pausa REAL entre la lectura ('arrived') y la escritura de la
        cancelación; el mensajero sella 'delivered' (recogida de 1.500 USD)
        en medio. La cancelación pierde, el movimiento se conserva y queda
        incidencia visible."""
        dep = _plant_deposit(status="rejected")
        did, _ = _plant_delivery(status="arrived", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)

        async def _f():
            import services.deliveries as sd
            real_db = sd.db
            hit, go = asyncio.Event(), asyncio.Event()
            state = {"n": 0}

            class _Deliveries:
                def __getattr__(self, n):
                    return getattr(real_db.deliveries, n)

                async def update_one(self, q, u, **kw):
                    sets = (u.get("$set") or {})
                    if sets.get("status") == "cancelled" and state["n"] == 0:
                        state["n"] = 1
                        hit.set()
                        await go.wait()
                    return await real_db.deliveries.update_one(q, u, **kw)

            class _DB:
                deliveries = _Deliveries()

                def __getattr__(self, n):
                    return getattr(real_db, n)

                def __getitem__(self, n):
                    return real_db[n]

            sd.db = _DB()
            try:
                task = asyncio.create_task(sd.handle_origin_rejected(
                    "deposit", dep, note="depósito rechazado"))
                await hit.wait()
                # El sello de la recogida gana la carrera (escritura real).
                now = _iso()
                await real_db.deliveries.update_one(
                    {"id": did, "status": "arrived"},
                    {"$set": {"status": "delivered", "updated_at": now},
                     "$push": {"timeline": {"status": "delivered",
                                            "at": now, "by": COURIER_A}}})
                go.set()
                return await task
            finally:
                sd.db = real_db

        outcome = _run(_f)
        assert outcome == "conflict", \
            f"la recogida sellada debe ganar con incidencia, no '{outcome}'"
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "delivered", \
            "el movimiento físico registrado JAMÁS se oculta"
        assert d.get("origin_conflict"), "incidencia visible y trazable"

    def test_reject_endpoint_after_sealed_pickup_keeps_incident(self):
        """End-to-end por el endpoint real: depósito pendiente con recogida
        ya sellada → el rechazo deja incidencia, no cancela, y la tarea
        durable queda cerrada con un resultado persistente."""
        dep = _plant_deposit(status="pending")
        did, _ = _plant_delivery(status="delivered", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)
        r = requests.post(f"{API}/admin/deposits/{dep}/reject",
                          headers=_hdr(), json={"admin_note": f"{MARK} test"})
        assert r.status_code == 200, r.text
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "delivered"
        assert d.get("origin_conflict")
        doc = _db().deposits.find_one({"id": dep})
        assert doc["status"] == "rejected"
        assert not doc.get("delivery_cancel_pending"), \
            "con incidencia persistente la tarea puede cerrarse"

    def test_cancel_still_wins_before_physical_movement(self):
        """Control: sin movimiento físico la cancelación procede normal."""
        dep = _plant_deposit(status="rejected")
        did, _ = _plant_delivery(status="accepted", courier_id=COURIER_A,
                                 kind="deposit", ref_id=dep)

        async def _f():
            from services.deliveries import handle_origin_rejected
            return await handle_origin_rejected("deposit", dep,
                                                note="depósito rechazado")
        outcome = _run(_f)
        assert outcome == "cancelled"
        d = _db().deliveries.find_one({"id": did})
        assert d["status"] == "cancelled" and not d.get("origin_conflict")


# ============================================================
# MS04 — las métricas agregan TODOS los documentos del filtro
# ============================================================

class TestMS04MetricsNoCap:
    COURIER_M = "it295_courier_m"

    def test_metrics_aggregate_2001_confirmed(self):
        _mk_user(self.COURIER_M, is_courier=True)
        db = _db()
        now = _iso()
        docs = []
        for i in range(2001):
            rid = f"it295_ref_m{i}"
            docs.append({
                "id": f"it295_d_m{i}", "kind": "redemption", "ref_id": rid,
                "active_key": f"redemption:{rid}",
                "user_id": CLIENT_ID, "client_name": f"{MARK} client",
                "amount_label": f"{MARK} shipment", "km": 20.0,
                "fee_usdt": 10.0, "courier_share_usdt": 8.0,
                "platform_share_usdt": 2.0, "status": "confirmed",
                "courier_id": self.COURIER_M, "courier_name": f"{MARK} courier",
                "payout_credited": True,
                "fee_paid_usdt": 10.0, "courier_share_paid_usdt": 8.0,
                "platform_share_paid_usdt": 2.0,
                "created_at": now, "updated_at": now,
                "timeline": [],
            })
        # El ÚNICO registro con incidencia queda FUERA de las primeras
        # 2.000 filas: tampoco puede desaparecer de la estadística.
        docs[-1]["incidents"] = [{"note": f"{MARK} incidencia", "at": now}]
        db.deliveries.insert_many(docs)
        r = requests.get(
            f"{API}/admin/deliveries/metrics?courier_id={self.COURIER_M}",
            headers=_hdr())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2001, f"2.001 de 2.001, no {body['total']}"
        assert body["confirmed"] == 2001
        assert body["fees_usdt"] == 20010.0, \
            f"tarifas completas 20.010, no {body['fees_usdt']}"
        assert body["courier_paid_usdt"] == 16008.0
        assert body["platform_net_usdt"] == 4002.0
        assert body["incidents_count"] == 1, \
            "la incidencia fuera de las primeras 2.000 filas no desaparece"

    def test_metrics_and_summary_agree_on_same_universe(self):
        """El resumen diario y las métricas coinciden cuando sus filtros
        seleccionan el mismo conjunto (las 2.001 del test anterior siguen
        plantadas hasta el teardown del módulo)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r1 = requests.get(f"{API}/admin/deliveries/summary?date={today}",
                          headers=_hdr())
        r2 = requests.get(
            f"{API}/admin/deliveries/metrics?courier_id={self.COURIER_M}"
            f"&date_from={today}&date_to={today}", headers=_hdr())
        assert r1.status_code == 200 and r2.status_code == 200
        # El summary es global del día; las métricas filtradas por mensajero
        # de prueba deben reportar al menos las 2.001 confirmadas de it295.
        assert r2.json()["confirmed"] >= 2001
        assert r1.json()["confirmed_count"] >= r2.json()["confirmed"] or \
            r1.json()["confirmed_count"] >= 2001
