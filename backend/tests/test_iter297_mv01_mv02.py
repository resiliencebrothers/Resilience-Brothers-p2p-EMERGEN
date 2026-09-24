"""iter297 — Verificación de mensajería 79224d6: MV01/MV02.

MV01 · La decisión de sincronización más reciente («ajustar a X» o «no hay
diferencia») avanza una revisión monotónica PERSISTENTE
(`fee_adjustment_rev`), independiente de que el ajuste exista: un escritor
antiguo que reanuda no puede recrear un ajuste obsoleto después de volver a
la tarifa ya liquidada.
MV02 · Publicación en dos fases: el reparto nace NO aceptable
(`needs_origin_check`) hasta validar el origen; si la validación
post-inserción falla por un corte, la intención persiste en el documento y
`heal_unvalidated_deliveries` lo converge — un cargo anulado jamás queda
operable ni pagable, y la recuperación no depende de una lectura aislada.
"""
import asyncio
import os
import uuid

from pymongo import MongoClient

from tests.conftest import BASE_URL  # noqa: F401 — entorno de test
from tests.test_iter279_s01_s07 import _run

MARK = "IT297"
COURIER_A = "it297_courier_a"
CLIENT_ID = "it297_client"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _mk_user(uid, is_courier=False):
    _db().users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "email": f"{uid}@it297.test", "name": f"{MARK} {uid}",
        "role": "vip", "account_status": "active", "is_verified": True,
        "is_courier": is_courier, "vip_balances": {}}}, upsert=True)


def _plant_delivery(status="available", courier_id=None, ref_id=None,
                    fee=10.0, extra=None):
    did = f"it297_d_{uuid.uuid4().hex[:10]}"
    rid = ref_id or f"it297_ref_{uuid.uuid4().hex[:10]}"
    now = _iso()
    doc = {
        "id": did, "kind": "redemption", "ref_id": rid,
        "active_key": f"redemption:{rid}",
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


def _cleanup():
    db = _db()
    db.deliveries.delete_many({"$or": [{"id": {"$regex": "^it297_"}},
                                       {"ref_id": {"$regex": "^it297_"}}]})
    db.redemptions.delete_many({"id": {"$regex": "^it297_"}})
    db.users.delete_many({"user_id": {"$regex": "^it297_"}})
    db.notifications.delete_many({"message": {"$regex": "it297_"}})
    db.notifications.delete_many({"title": {"$regex": MARK}})


def setup_module(module):
    _cleanup()
    _mk_user(COURIER_A, is_courier=True)
    _mk_user(CLIENT_ID)


def teardown_module(module):
    _cleanup()


def _upsert(rid, fee, rev, km=20.0):
    async def _f():
        from services.deliveries import upsert_delivery_for_charge
        return await upsert_delivery_for_charge(
            "redemption", {"id": rid}, km=km, fee_usdt=fee, fee_rev=rev)
    return _run(_f)


def _paused_adjustment_write(rid, stale_fee, stale_rev, during_pause):
    """Pausa al escritor ANTIGUO justo antes de guardar su ajuste
    (fee_adjustment_pending) — la ventana exacta de MV01 — y corre la
    decisión más nueva en medio."""
    async def _f():
        import services.deliveries as sd
        real_db = sd.db
        hit, go = asyncio.Event(), asyncio.Event()

        class _Deliveries:
            def __getattr__(self, n):
                return getattr(real_db.deliveries, n)

            async def update_one(self, q, u, **kw):
                adj = (u.get("$set") or {}).get("fee_adjustment_pending")
                if adj and adj.get("fee_usdt") == stale_fee \
                        and not hit.is_set():
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
            task = asyncio.create_task(sd.upsert_delivery_for_charge(
                "redemption", {"id": rid}, km=20.0, fee_usdt=stale_fee,
                fee_rev=stale_rev))
            await hit.wait()
            await during_pause(sd, real_db)
            go.set()
            return await task
        finally:
            sd.db = real_db
    return _run(_f)


# ============================================================
# MV01 — la decisión «sin ajuste» cerca a escritores antiguos
# ============================================================

class TestMV01PersistentAdjustmentRev:
    def teardown_method(self, _):
        _cleanup()

    def test_no_adjust_decision_fences_old_writer(self):
        """Reproducción A del informe: sin ajuste previo, el escritor de la
        tarifa 20 (rev 2) queda pausado; la decisión más nueva (volver a 10,
        rev 3 — sin diferencia con los 8 pagados) debe cercarlo: al reanudar
        NO puede crear el ajuste obsoleto."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1})
        _plant_redemption(rid, fee=20.0, rev=2)

        async def _newer_decision(sd, real_db):
            await real_db.redemptions.update_one(
                {"id": rid}, {"$set": {"courier_fee_usdt": 10.0,
                                       "courier_fee_usd": 10.0,
                                       "courier_fee_rev": 3}})
            # La decisión nueva: objetivo == pagado → sin ajuste, pero la
            # revisión debe avanzar igualmente.
            await sd.upsert_delivery_for_charge(
                "redemption", {"id": rid}, km=20.0, fee_usdt=10.0, fee_rev=3)

        _paused_adjustment_write(rid, stale_fee=20.0, stale_rev=2,
                                 during_pause=_newer_decision)
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("fee_adjustment_pending"), \
            "un ajuste obsoleto JAMÁS reaparece tras la decisión de no ajustar"
        assert d.get("fee_adjustment_rev") == 3, \
            "la decisión «sin diferencia» también avanza la revisión"
        assert d["courier_share_paid_usdt"] == 8.0
        # Dos pasadas del recuperador no cambian nada.
        async def _heal():
            from services.deliveries import heal_unvalidated_deliveries
            await heal_unvalidated_deliveries()
        _run(_heal)
        _run(_heal)
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("fee_adjustment_pending")

    def test_removed_adjustment_stays_removed(self):
        """Reproducción B: existe un ajuste (30→24); el escritor del cambio
        a 20 queda pausado; una decisión más nueva (volver a 10) retira el
        ajuste. Al reanudar, el escritor antiguo no puede recrearlo."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1})
        _plant_redemption(rid, fee=30.0, rev=2)
        _upsert(rid, fee=30.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        assert d["fee_adjustment_pending"]["courier_share_usdt"] == 24.0

        async def _newer_decision(sd, real_db):
            await real_db.redemptions.update_one(
                {"id": rid}, {"$set": {"courier_fee_usdt": 10.0,
                                       "courier_fee_usd": 10.0,
                                       "courier_fee_rev": 4}})
            await sd.upsert_delivery_for_charge(
                "redemption", {"id": rid}, km=20.0, fee_usdt=10.0, fee_rev=4)
            cur = await real_db.deliveries.find_one({"id": did})
            assert not cur.get("fee_adjustment_pending"), \
                "la decisión nueva retira el ajuste"

        _paused_adjustment_write(rid, stale_fee=20.0, stale_rev=3,
                                 during_pause=_newer_decision)
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("fee_adjustment_pending"), \
            f"el escritor antiguo (rev 3) no puede recrearlo: {d.get('fee_adjustment_pending')}"
        assert d.get("fee_adjustment_rev") == 4

    def test_old_adjustment_between_no_adjust_read_and_write_is_removed(self):
        """Variante del informe 52236b1: el escritor antiguo (tarifa 20,
        rev 2) cuela su ajuste ENTRE la comprobación de la decisión «sin
        ajuste» (tarifa 10, rev 3) y su escritura. La decisión nueva es UNA
        sola escritura indivisible: retira el ajuste colado igualmente.
        Final: tarifa 10, pago 8, revisión persistente 3, NINGÚN ajuste."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1})
        _plant_redemption(rid, fee=20.0, rev=2)

        async def _f():
            import services.deliveries as sd
            real_db = sd.db
            old_hit, old_go = asyncio.Event(), asyncio.Event()
            fresh_hit, fresh_go = asyncio.Event(), asyncio.Event()

            class _Deliveries:
                def __getattr__(self, n):
                    return getattr(real_db.deliveries, n)

                async def update_one(self, q, u, **kw):
                    adj = (u.get("$set") or {}).get("fee_adjustment_pending")
                    if adj and adj.get("fee_usdt") == 20.0 \
                            and not old_hit.is_set():
                        old_hit.set()
                        await old_go.wait()
                    return await real_db.deliveries.update_one(q, u, **kw)

                async def find_one_and_update(self, q, u, **kw):
                    if "fee_adjustment_pending" in (u.get("$unset") or {}) \
                            and not fresh_hit.is_set():
                        fresh_hit.set()
                        await fresh_go.wait()
                    return await real_db.deliveries.find_one_and_update(
                        q, u, **kw)

            class _DB:
                deliveries = _Deliveries()

                def __getattr__(self, n):
                    return getattr(real_db, n)

                def __getitem__(self, n):
                    return real_db[n]

            sd.db = _DB()
            try:
                old = asyncio.create_task(sd.upsert_delivery_for_charge(
                    "redemption", {"id": rid}, km=20.0, fee_usdt=20.0,
                    fee_rev=2))
                await old_hit.wait()
                # Decisión nueva: volver a 10 (rev 3) — pausada justo antes
                # de SU escritura «sin ajuste».
                await real_db.redemptions.update_one(
                    {"id": rid}, {"$set": {"courier_fee_usdt": 10.0,
                                           "courier_fee_usd": 10.0,
                                           "courier_fee_rev": 3}})
                fresh = asyncio.create_task(sd.upsert_delivery_for_charge(
                    "redemption", {"id": rid}, km=20.0, fee_usdt=10.0,
                    fee_rev=3))
                await fresh_hit.wait()
                # El escritor antiguo guarda su ajuste (16, rev 2) en medio…
                old_go.set()
                await old
                cur = await real_db.deliveries.find_one({"id": did})
                assert (cur.get("fee_adjustment_pending") or {}).get(
                    "courier_share_usdt") == 16.0, \
                    "precondición: el ajuste viejo quedó colado"
                # …y la decisión nueva se reanuda: su única escritura lo
                # retira de forma indivisible.
                fresh_go.set()
                await fresh
            finally:
                sd.db = real_db
        _run(_f)
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("fee_adjustment_pending"), \
            "el ajuste colado entre lecturas DEBE quedar retirado"
        assert d.get("fee_adjustment_rev") == 3
        assert d["courier_share_paid_usdt"] == 8.0
        # Recuperar y repetir la revisión vigente: sin duplicados.
        _upsert(rid, fee=10.0, rev=3)
        _upsert(rid, fee=10.0, rev=3)
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("fee_adjustment_pending")
        resolved = [e for e in d["timeline"]
                    if e.get("status") == "fee_conflict_resolved"]
        assert len(resolved) == 1, "una sola nota de cierre, sin duplicados"

    def test_incoherent_row_repaired_by_current_revision_replay(self):
        """Fila YA incoherente (revisión vigente 2 con ajuste obsoleto de
        rev 1 dentro): repetir la sincronización de la revisión vigente la
        repara — el ajuste obsoleto se retira."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1, "fee_adjustment_rev": 2,
                   "fee_adjustment_pending": {
                       "fee_usdt": 20.0, "courier_share_usdt": 16.0,
                       "fee_rev": 1, "at": _iso()}})
        _plant_redemption(rid, fee=10.0, rev=2)

        async def _sync():
            from services.deliveries import sync_delivery_from_doc
            await sync_delivery_from_doc("redemptions", rid)
        _run(_sync)
        d = _db().deliveries.find_one({"id": did})
        assert not d.get("fee_adjustment_pending"), \
            "la reparación retira el ajuste obsoleto de la fila incoherente"
        assert d.get("fee_adjustment_rev") == 2
        assert d["courier_share_paid_usdt"] == 8.0

    def test_repair_never_deletes_newer_legitimate_adjustment(self):
        """Control: una decisión «sin ajuste» ATRASADA (rev 2) no puede
        borrar un ajuste legítimo más nuevo (rev 3)."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1, "fee_adjustment_rev": 3,
                   "fee_adjustment_pending": {
                       "fee_usdt": 30.0, "courier_share_usdt": 24.0,
                       "fee_rev": 3, "at": _iso()}})
        _plant_redemption(rid, fee=10.0, rev=2)
        _upsert(rid, fee=10.0, rev=2)
        d = _db().deliveries.find_one({"id": did})
        adj = d.get("fee_adjustment_pending")
        assert adj and adj["courier_share_usdt"] == 24.0 \
            and adj["fee_rev"] == 3, \
            "el ajuste legítimo más nuevo permanece intacto"
        assert d.get("fee_adjustment_rev") == 3

    def test_positive_chain_still_updates_to_latest(self):
        """Control: la cadena positiva 10→20→30 sigue dejando objetivo 24 y
        una repetición de la misma revisión no duplica nada."""
        did, rid = _plant_delivery(
            status="confirmed", courier_id=COURIER_A, fee=10.0,
            extra={"payout_credited": True, "courier_share_paid_usdt": 8.0,
                   "fee_paid_usdt": 10.0, "platform_share_paid_usdt": 2.0,
                   "fee_rev": 1})
        _plant_redemption(rid, fee=20.0, rev=2)
        _upsert(rid, fee=20.0, rev=2)
        _plant_redemption(rid, fee=30.0, rev=3)
        _upsert(rid, fee=30.0, rev=3)
        _upsert(rid, fee=30.0, rev=3)
        d = _db().deliveries.find_one({"id": did})
        adj = d.get("fee_adjustment_pending")
        assert adj and adj["courier_share_usdt"] == 24.0
        assert d.get("fee_adjustment_rev") == 3
        conflicts = [e for e in d["timeline"]
                     if e.get("status") == "fee_conflict"]
        assert len(conflicts) == 2, "una entrada por revisión, sin duplicados"


# ============================================================
# MV02 — la publicación no validada jamás es aceptable/pagable
# ============================================================

def _paused_insert_with_failing_postcheck(rid, stale_fee, stale_rev,
                                          concurrent):
    """Reproduce el orden exacto del informe: creación pausada antes de
    insertar → anulación concurrente (cierra su propia tarea) → inserción
    atrasada + UNA excepción en la lectura post-inserción del origen."""
    async def _f():
        import services.deliveries as sd
        real_db = sd.db
        hit, go = asyncio.Event(), asyncio.Event()
        state = {"paused": False, "postcheck_failures": 0}

        class _Deliveries:
            def __getattr__(self, n):
                return getattr(real_db.deliveries, n)

            async def insert_one(self, doc):
                if not state["paused"]:
                    state["paused"] = True
                    hit.set()
                    await go.wait()
                return await real_db.deliveries.insert_one(doc)

        class _Redemptions:
            def __getattr__(self, n):
                return getattr(real_db.redemptions, n)

            async def find_one(self, q, projection=None, **kw):
                if projection and "courier_fee_rev" in projection \
                        and state["paused"] \
                        and state["postcheck_failures"] == 0:
                    state["postcheck_failures"] += 1
                    raise RuntimeError(
                        "fallo sintético de la lectura post-inserción")
                return await real_db.redemptions.find_one(q, projection, **kw)

        class _DB:
            deliveries = _Deliveries()
            redemptions = _Redemptions()

            def __getattr__(self, n):
                return getattr(real_db, n)

            def __getitem__(self, n):
                if n == "redemptions":
                    return self.redemptions
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
            result = await task
            return result, state["postcheck_failures"]
        finally:
            sd.db = real_db
    return _run(_f)


def _claim_as_courier(did):
    async def _f():
        import routes.deliveries as dr
        orig = dr._require_courier

        async def fake_rc(request):
            return {"user_id": COURIER_A, "name": f"{MARK} courier",
                    "email": f"{COURIER_A}@it297.test", "role": "vip",
                    "is_courier": True}
        dr._require_courier = fake_rc
        try:
            try:
                return 200, await dr.claim_delivery(did, None)
            except dr.HTTPException as ex:
                return ex.status_code, ex.detail
        finally:
            dr._require_courier = orig
    return _run(_f)


class TestMV02PersistentIntent:
    def teardown_method(self, _):
        _cleanup()

    def test_failed_postcheck_leaves_unclaimable_then_heals_to_cancelled(self):
        """Criterio de aceptación del informe: fallo inmediatamente después
        de insertar y antes de validar el origen. El reparto NO puede ser
        aceptado ni pagar comisión sobre la tarifa anulada; tras recuperar
        converge a cancelado."""
        rid = f"it297_ref_{uuid.uuid4().hex[:10]}"
        _plant_redemption(rid, fee=20.0, rev=1)

        async def _annul(sd, real_db):
            await real_db.redemptions.update_one(
                {"id": rid}, {"$set": {"courier_fee_usdt": 0.0,
                                       "courier_fee_usd": 0.0,
                                       "courier_fee_rev": 2}})
            # La sincronización de la anulación no ve reparto y cierra su
            # propia tarea (no queda delivery_sync_pending).
            res = await sd.upsert_delivery_for_charge(
                "redemption", {"id": rid}, km=0.0, fee_usdt=0.0, fee_rev=2)
            assert res is None

        _result, failures = _paused_insert_with_failing_postcheck(
            rid, stale_fee=20.0, stale_rev=1, concurrent=_annul)
        assert failures == 1, "la lectura post-inserción falló exactamente una vez"
        d = _db().deliveries.find_one({"ref_id": rid})
        assert d is not None and d["status"] == "available"
        assert d.get("needs_origin_check") is True, \
            "la intención persistente DEBE sobrevivir al fallo de la lectura"
        # NO aceptable mientras esté pendiente de validar.
        code, detail = _claim_as_courier(d["id"])
        assert code == 409, f"un cargo anulado jamás es aceptable: {code} {detail}"
        # El recuperador converge SIN depender de tareas del origen.
        async def _heal():
            from services.deliveries import heal_unvalidated_deliveries
            return await heal_unvalidated_deliveries()
        assert _run(_heal) >= 1
        _run(_heal)
        d = _db().deliveries.find_one({"ref_id": rid})
        assert d["status"] == "cancelled", \
            "tras recuperar debe converger a cancelado"
        assert d["fee_rev"] == 2 and not d.get("needs_origin_check")
        assert not d.get("active_key")
        code, _detail = _claim_as_courier(d["id"])
        assert code == 409, "cancelado: sigue sin ser aceptable ni pagable"
        src = _db().redemptions.find_one({"id": rid})
        assert float(src["courier_fee_usdt"]) == 0.0

    def test_successful_postcheck_publishes_claimable(self):
        """Control: con la validación exitosa el reparto queda liberado
        (sin flag) y aceptable de inmediato."""
        rid = f"it297_ref_{uuid.uuid4().hex[:10]}"
        _plant_redemption(rid, fee=20.0, rev=1)
        doc = _upsert(rid, fee=20.0, rev=1)
        assert doc and doc["status"] == "available"
        d = _db().deliveries.find_one({"ref_id": rid})
        assert not d.get("needs_origin_check"), \
            "validado en línea: el flag no debe quedar en pie"
        code, body = _claim_as_courier(d["id"])
        assert code == 200 and body["status"] == "accepted"

    def test_healer_converges_to_newer_positive_fee(self):
        """El mismo corte contra una tarifa MÁS NUEVA positiva: el healer
        converge el reparto a la tarifa vigente y lo libera."""
        rid = f"it297_ref_{uuid.uuid4().hex[:10]}"
        _plant_redemption(rid, fee=20.0, rev=1)

        async def _newer(sd, real_db):
            await real_db.redemptions.update_one(
                {"id": rid}, {"$set": {"courier_fee_usdt": 30.0,
                                       "courier_fee_usd": 30.0,
                                       "courier_fee_rev": 2}})

        _paused_insert_with_failing_postcheck(
            rid, stale_fee=20.0, stale_rev=1, concurrent=_newer)
        d = _db().deliveries.find_one({"ref_id": rid})
        assert d.get("needs_origin_check") is True and d["fee_usdt"] == 20.0

        async def _heal():
            from services.deliveries import heal_unvalidated_deliveries
            await heal_unvalidated_deliveries()
        _run(_heal)
        d = _db().deliveries.find_one({"ref_id": rid})
        assert d["fee_usdt"] == 30.0 and d["fee_rev"] == 2
        assert not d.get("needs_origin_check")
        code, body = _claim_as_courier(d["id"])
        assert code == 200 and body["fee_usdt"] == 30.0
