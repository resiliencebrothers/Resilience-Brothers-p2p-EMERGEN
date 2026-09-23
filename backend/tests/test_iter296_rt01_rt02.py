"""iter296 — Verificación RT01/RT02 (informe 08ba024).

RT01 · El recuperador NO puede cerrar como fallida una operación cuyo
ejecutor sigue vivo sin bloquear su asiento: el cierre sepulta el marcador
atómicamente en el doc del usuario (mismo doc que decide el gasto) y el
asiento excluye marcadores sepultados. Solo hay dos resultados coherentes:
fallida sin movimiento, o aplicada con un solo movimiento y comprobante
recuperable — jamás dinero movido con registro fallido.
RT02 · La identidad del intento (op_id) se conserva ante 5xx y ante 409
CONVERSION_IN_PROGRESS: el reintento con la misma clave recupera el
comprobante original — nunca una segunda conversión ni segunda comisión.
"""
import asyncio
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, make_admin_totp
from tests.test_iter279_s01_s07 import _run

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _snapshot_vip():
    u = _db().users.find_one(
        {"user_id": VIP_ID},
        {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1,
         "recent_conversion_ids": 1, "cancelled_conversion_markers": 1})
    return {"vip_balances": (u or {}).get("vip_balances") or {},
            "vip_balance_usd": float((u or {}).get("vip_balance_usd") or 0.0),
            "recent_conversion_ids":
                (u or {}).get("recent_conversion_ids") or [],
            "cancelled_conversion_markers":
                (u or {}).get("cancelled_conversion_markers") or []}


def _restore_vip(snap):
    _db().users.update_one({"user_id": VIP_ID}, {"$set": snap})


def _set_vip(balances, legacy_usd=0.0):
    _db().users.update_one(
        {"user_id": VIP_ID},
        {"$set": {"vip_balances": balances, "vip_balance_usd": legacy_usd}})


def _vip_balances():
    u = _db().users.find_one({"user_id": VIP_ID},
                             {"_id": 0, "vip_balances": 1})
    return dict((u or {}).get("vip_balances") or {})


def _vip_user_doc():
    u = _db().users.find_one({"user_id": VIP_ID}, {"_id": 0})
    assert u, "usuario VIP de prueba ausente"
    return u


def _mk_currency(code, type_="fiat", **kw):
    r = requests.post(f"{API}/admin/currencies", headers=_hdr(ADMIN_TOKEN),
                      json={"code": code, "name": f"IT296 {code}",
                            "type": type_, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_rate(from_code, to_code, normal, vip=None):
    r = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN),
                      json={"from_code": from_code, "to_code": to_code,
                            "rate_normal": normal,
                            "rate_vip": vip if vip is not None else normal,
                            "totp_code": make_admin_totp()})
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup_market():
    db = _db()
    db.rates.delete_many({"$or": [{"from_code": {"$regex": "^IT296"}},
                                  {"to_code": {"$regex": "^IT296"}}]})
    db.currencies.delete_many({"code": {"$regex": "^IT296"}})
    db.conversions.delete_many({"user_id": VIP_ID,
                                "$or": [{"from_code": {"$regex": "^IT296"}},
                                        {"to_code": {"$regex": "^IT296"}},
                                        {"op_id": {"$regex": "^it296"}},
                                        {"marker_id": {"$regex": "^it296"}}]})
    db.audit_log.delete_many({"actor_id": VIP_ID,
                              "action": {"$in": ["vip.convert",
                                                 "vip.convert.dust"]},
                              "$or": [{"details.from_code":
                                       {"$regex": "^IT296"}},
                                      {"details.to_code":
                                       {"$regex": "^IT296"}}]})
    db.users.update_one(
        {"user_id": VIP_ID},
        {"$pull": {"cancelled_conversion_markers": {"$regex": "^it296"}}})


def _convert_http(body, tok=VIP_TOKEN):
    return requests.post(f"{API}/vip/convert", headers=_hdr(tok), json=body)


def _paused_route_with_heal(route_call, stale_user, during_pause):
    """Ejecuta una ruta de orders pausando su asiento (users.update_one)
    ENTRE el registro durable y la escritura monetaria — la ventana exacta
    de RT01 — y corre `during_pause()` (el recuperador) en medio."""
    async def _f():
        import routes.orders as om
        real_db = om.db
        hit, go = asyncio.Event(), asyncio.Event()
        state = {"n": 0}

        class _Users:
            def __getattr__(self, n):
                return getattr(real_db.users, n)

            async def update_one(self, q, u, **kw):
                if state["n"] == 0 and q.get("user_id") == VIP_ID:
                    state["n"] = 1
                    hit.set()
                    await go.wait()
                return await real_db.users.update_one(q, u, **kw)

        class _DB:
            users = _Users()

            def __getattr__(self, n):
                return getattr(real_db, n)

            def __getitem__(self, n):
                return real_db[n]

        orig_ru = om.require_user

        async def fake_ru(request):
            return dict(stale_user)

        om.require_user = fake_ru
        om.db = _DB()
        try:
            async def _call():
                try:
                    return 200, await route_call(om)
                except om.HTTPException as ex:
                    return ex.status_code, ex.detail
            task = asyncio.create_task(_call())
            await hit.wait()
            await during_pause()
            go.set()
            return await task
        finally:
            om.db = real_db
            om.require_user = orig_ru
    return _run(_f)


async def _heal_all():
    from services.conversions import heal_pending_conversions
    await heal_pending_conversions(max_age_seconds=-1)


# ============================================================
# RT01 — el cierre del recuperador bloquea el asiento atrasado
# ============================================================

class TestRT01CoordinatedClose:
    def teardown_method(self, _):
        _cleanup_market()

    def test_healer_blocks_late_convert_write(self):
        """Orden exacto del informe: «solicitud detenida → vencimiento →
        recuperación → el escritor original continúa». El asiento atrasado
        DEBE quedar bloqueado: fallida SIN ningún movimiento."""
        _cleanup_market()
        snap = _snapshot_vip()
        op = f"it296-rt01-{uuid.uuid4().hex[:8]}"
        try:
            _mk_currency("IT296A")
            _mk_rate("USDT", "IT296A", 100, 100)
            _set_vip({"USDT": 100.0})
            stale = _vip_user_doc()
            code, detail = _paused_route_with_heal(
                lambda om: om.vip_convert(om.VipConvertPayload(
                    from_code="USDT", to_code="IT296A", amount_from=10.0,
                    op_id=op), None),
                stale, _heal_all)
            assert code == 409 and detail.get("code") == "CONVERSION_EXPIRED", \
                f"el asiento atrasado debe quedar bloqueado, no {code} {detail}"
            bal = _vip_balances()
            assert bal.get("USDT") == 100.0 and not bal.get("IT296A"), \
                f"fallida SIN movimiento: {bal}"
            doc = _db().conversions.find_one({"user_id": VIP_ID, "op_id": op})
            assert doc["status"] == "failed"
            u = _db().users.find_one({"user_id": VIP_ID},
                                     {"_id": 0,
                                      "cancelled_conversion_markers": 1})
            assert doc["marker_id"] in \
                (u.get("cancelled_conversion_markers") or [])
            # Recuperar dos veces más no cambia nada.
            _run(_heal_all)
            _run(_heal_all)
            assert _vip_balances().get("USDT") == 100.0
            assert _db().conversions.find_one(
                {"user_id": VIP_ID, "op_id": op})["status"] == "failed"
            # El mismo op_id devuelve el cierre definitivo (nada se movió).
            r = _convert_http({"from_code": "USDT", "to_code": "IT296A",
                               "amount_from": 10.0, "op_id": op})
            assert r.status_code == 409 \
                and r.json()["detail"]["code"] == "OP_ID_CLOSED"
        finally:
            _restore_vip(snap)

    def test_healer_blocks_late_dust_write(self):
        """La misma ventana en el barrido de polvo: fallida sin movimiento
        ni comisión."""
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT296D")
            _mk_rate("USDT", "IT296D", 100, 100)
            _set_vip({"USDT": 1.0, "IT296D": 300.0})
            stale = _vip_user_doc()
            code, detail = _paused_route_with_heal(
                lambda om: om.vip_convert_dust(None, None),
                stale, _heal_all)
            assert code == 409 and detail.get("code") == "CONVERSION_EXPIRED", \
                f"{code} {detail}"
            bal = _vip_balances()
            assert bal.get("USDT") == 1.0 and bal.get("IT296D") == 300.0, \
                f"ni movimiento ni comisión: {bal}"
            rows = list(_db().conversions.find(
                {"user_id": VIP_ID, "from_code": "IT296D"}))
            assert rows and all(r["status"] == "failed" for r in rows)
        finally:
            _restore_vip(snap)

    def test_executor_beats_healer_resolves_applied(self):
        """Intercalado inverso: el ejecutor gasta el marcador ENTRE la
        lectura del recuperador y su entierro. El recuperador debe resolver
        APLICADA (jamás fallida con dinero movido) y el comprobante queda
        recuperable con el mismo op_id."""
        _cleanup_market()
        snap = _snapshot_vip()
        op = f"it296-rt01b-{uuid.uuid4().hex[:8]}"
        try:
            _mk_currency("IT296B")
            _mk_rate("USDT", "IT296B", 100, 100)
            _set_vip({"USDT": 100.0})
            stale = _vip_user_doc()

            async def _f():
                import routes.orders as om
                import services.conversions as sc
                real_db = om.db
                ex_hit, ex_go = asyncio.Event(), asyncio.Event()
                h_hit, h_go = asyncio.Event(), asyncio.Event()
                ex_state = {"n": 0}

                class _ExUsers:
                    def __getattr__(self, n):
                        return getattr(real_db.users, n)

                    async def update_one(self, q, u, **kw):
                        if ex_state["n"] == 0 and q.get("user_id") == VIP_ID:
                            ex_state["n"] = 1
                            ex_hit.set()
                            await ex_go.wait()
                        return await real_db.users.update_one(q, u, **kw)

                class _ExDB:
                    users = _ExUsers()

                    def __getattr__(self, n):
                        return getattr(real_db, n)

                    def __getitem__(self, n):
                        return real_db[n]

                orig_ru = om.require_user

                async def fake_ru(request):
                    return dict(stale)

                om.require_user = fake_ru
                om.db = _ExDB()
                try:
                    async def _call():
                        try:
                            return 200, await om.vip_convert(
                                om.VipConvertPayload(
                                    from_code="USDT", to_code="IT296B",
                                    amount_from=10.0, op_id=op), None)
                        except om.HTTPException as ex:
                            return ex.status_code, ex.detail
                    task = asyncio.create_task(_call())
                    await ex_hit.wait()
                    conv = await real_db.conversions.find_one(
                        {"user_id": VIP_ID, "op_id": op}, {"_id": 0})
                    marker = conv["marker_id"]

                    class _HUsers:
                        def __getattr__(self, n):
                            return getattr(real_db.users, n)

                        async def update_one(self, q, u, **kw):
                            adds = (u.get("$addToSet") or {})
                            if adds.get("cancelled_conversion_markers") \
                                    == marker:
                                h_hit.set()
                                await h_go.wait()
                            return await real_db.users.update_one(q, u, **kw)

                    class _HDB:
                        users = _HUsers()

                        def __getattr__(self, n):
                            return getattr(real_db, n)

                        def __getitem__(self, n):
                            return real_db[n]

                    sc.db = _HDB()
                    try:
                        heal_task = asyncio.create_task(
                            sc.heal_pending_conversions(max_age_seconds=-1))
                        # El recuperador ya leyó «marcador no gastado» y está
                        # a punto de sepultarlo…
                        await h_hit.wait()
                        # …pero el ejecutor termina su asiento primero.
                        ex_go.set()
                        result = await task
                        h_go.set()
                        await heal_task
                        return result
                    finally:
                        sc.db = real_db
                finally:
                    om.db = real_db
                    om.require_user = orig_ru

            code, body = _run(_f)
            assert code == 200 and body.get("ok"), f"{code} {body}"
            doc = _db().conversions.find_one({"user_id": VIP_ID, "op_id": op})
            assert doc["status"] == "applied", \
                "el movimiento ganó → el registro DEBE quedar aplicado"
            bal = _vip_balances()
            assert abs(bal["USDT"] - 89.99) < 1e-9 \
                and bal.get("IT296B") == 1000.0, f"un solo movimiento: {bal}"
            u = _db().users.find_one({"user_id": VIP_ID},
                                     {"_id": 0,
                                      "cancelled_conversion_markers": 1})
            assert doc["marker_id"] not in \
                (u.get("cancelled_conversion_markers") or []), \
                "un marcador gastado jamás queda sepultado"
            # Comprobante recuperable con el mismo op_id.
            r = _convert_http({"from_code": "USDT", "to_code": "IT296B",
                               "amount_from": 10.0, "op_id": op})
            assert r.status_code == 200 and r.json()["duplicate"] \
                and r.json()["conversion_id"] == doc["id"]
            assert abs(_vip_balances()["USDT"] - 89.99) < 1e-9
        finally:
            _restore_vip(snap)

    def test_tombstones_pruned_after_safety_window(self):
        """Los marcadores sepultados prescriben pasada la ventana de
        seguridad; los recientes se conservan."""
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            db = _db()
            old = [f"it296_tomb_{i}" for i in range(24)]
            fresh = "it296_tomb_fresh"
            for m in old[:10]:
                db.conversions.insert_one({
                    "id": f"conv_{uuid.uuid4().hex}", "user_id": VIP_ID,
                    "marker_id": m, "status": "failed", "kind": "convert",
                    "from_code": "IT296X", "to_code": "USDT",
                    "created_at": "2020-01-01T00:00:00+00:00"})
            db.conversions.insert_one({
                "id": f"conv_{uuid.uuid4().hex}", "user_id": VIP_ID,
                "marker_id": fresh, "status": "failed", "kind": "convert",
                "from_code": "IT296X", "to_code": "USDT",
                "created_at": "2099-01-01T00:00:00+00:00"})
            db.users.update_one(
                {"user_id": VIP_ID},
                {"$set": {"cancelled_conversion_markers": old + [fresh]}})

            async def _prune():
                from services.conversions import prune_conversion_tombstones
                await prune_conversion_tombstones()
            _run(_prune)
            u = db.users.find_one({"user_id": VIP_ID},
                                  {"_id": 0, "cancelled_conversion_markers": 1})
            assert u["cancelled_conversion_markers"] == [fresh], \
                "viejos y huérfanos fuera; el reciente se conserva"
        finally:
            _db().conversions.delete_many(
                {"user_id": VIP_ID, "marker_id": {"$regex": "^it296_tomb"}})
            _restore_vip(snap)


# ============================================================
# RT02 — la identidad conservada convierte el reintento en
# recuperación del comprobante, nunca en segunda conversión
# ============================================================

class TestRT02StableIdentity:
    def teardown_method(self, _):
        _cleanup_market()

    def test_seal_failure_then_same_op_recovers_single_conversion(self):
        """Variante A end-to-end (lado servidor): el sello falla DESPUÉS del
        asiento (el cliente ve un 500). Con la identidad CONSERVADA, el
        reintento con la misma clave devuelve primero «en curso», el sanador
        resuelve, y el siguiente reintento recupera el comprobante: una sola
        conversión, una sola comisión, 89.99 USDT + 1.000 destino."""
        _cleanup_market()
        snap = _snapshot_vip()
        op = f"it296-rt02-{uuid.uuid4().hex[:8]}"
        try:
            _mk_currency("IT296C")
            _mk_rate("USDT", "IT296C", 100, 100)
            _set_vip({"USDT": 100.0})
            stale = _vip_user_doc()

            async def _call_with_seal_failure():
                import routes.orders as om
                import services.conversions as sc
                orig_mark = sc.mark_conversions
                orig_ru = om.require_user

                async def failing_mark(uid, marker, status):
                    if status == "applied":
                        raise RuntimeError(
                            "fallo sintético del sello tras el asiento")
                    return await orig_mark(uid, marker, status)

                async def fake_ru(request):
                    return dict(stale)

                sc.mark_conversions = failing_mark
                om.require_user = fake_ru
                try:
                    try:
                        await om.vip_convert(om.VipConvertPayload(
                            from_code="USDT", to_code="IT296C",
                            amount_from=10.0, op_id=op), None)
                        return "no-error"
                    except RuntimeError:
                        return "seal-failed"
                finally:
                    sc.mark_conversions = orig_mark
                    om.require_user = orig_ru

            assert _run(_call_with_seal_failure) == "seal-failed"
            bal = _vip_balances()
            assert abs(bal["USDT"] - 89.99) < 1e-9 \
                and bal.get("IT296C") == 1000.0, \
                "el dinero SÍ se movió antes del fallo del sello"
            assert _db().conversions.find_one(
                {"user_id": VIP_ID, "op_id": op})["status"] == "applying"
            # Reintento con la MISMA clave mientras sigue «en curso»: 409
            # informativo, JAMÁS una segunda conversión.
            body = {"from_code": "USDT", "to_code": "IT296C",
                    "amount_from": 10.0, "op_id": op}
            r = _convert_http(body)
            assert r.status_code == 409 and \
                r.json()["detail"]["code"] == "CONVERSION_IN_PROGRESS"
            assert _db().conversions.count_documents(
                {"user_id": VIP_ID, "op_id": op}) == 1
            _run(_heal_all)
            # Resuelta por el sanador (marcador gastado → aplicada): el
            # mismo op_id recupera el comprobante original.
            r = _convert_http(body)
            assert r.status_code == 200, r.text
            out = r.json()
            assert out["duplicate"] and out["amount_to"] == 1000.0
            bal = _vip_balances()
            assert abs(bal["USDT"] - 89.99) < 1e-9 \
                and bal["IT296C"] == 1000.0, \
                f"una sola conversión y una sola comisión: {bal}"
            rows = list(_db().conversions.find(
                {"user_id": VIP_ID, "to_code": "IT296C"}))
            assert len(rows) == 1 and rows[0]["status"] == "applied"
        finally:
            _restore_vip(snap)

    def test_in_progress_same_op_never_makes_second_conversion(self):
        """Variante B: primer intento pausado antes de su asiento; el
        reintento con la MISMA clave (identidad conservada) recibe 409
        «en curso» y NO ejecuta nada; al terminar el primero queda
        exactamente una conversión: 89.99 USDT + 1.000 destino."""
        _cleanup_market()
        snap = _snapshot_vip()
        op = f"it296-rt02b-{uuid.uuid4().hex[:8]}"
        try:
            _mk_currency("IT296E")
            _mk_rate("USDT", "IT296E", 100, 100)
            _set_vip({"USDT": 100.0})
            stale = _vip_user_doc()

            async def _retry_same_key():
                # Con la corrección RT02 el frontend CONSERVA la clave ante
                # el 409 «en curso»: este reintento la reutiliza tal cual.
                import routes.orders as om
                try:
                    await om.vip_convert(om.VipConvertPayload(
                        from_code="USDT", to_code="IT296E",
                        amount_from=10.0, op_id=op), None)
                    return None
                except om.HTTPException as ex:
                    return ex.status_code, ex.detail

            retry_result = {}

            async def _during_pause():
                import routes.orders as om
                orig_ru = om.require_user

                async def fake_ru(request):
                    return dict(stale)
                om.require_user = fake_ru
                try:
                    retry_result["r"] = await _retry_same_key()
                finally:
                    om.require_user = orig_ru

            code, body = _paused_route_with_heal(
                lambda om: om.vip_convert(om.VipConvertPayload(
                    from_code="USDT", to_code="IT296E", amount_from=10.0,
                    op_id=op), None),
                stale, _during_pause)
            assert code == 200 and body.get("ok"), f"{code} {body}"
            rcode, rdetail = retry_result["r"]
            assert rcode == 409 \
                and rdetail["code"] == "CONVERSION_IN_PROGRESS"
            bal = _vip_balances()
            assert abs(bal["USDT"] - 89.99) < 1e-9 \
                and bal.get("IT296E") == 1000.0, \
                f"exactamente una conversión: {bal}"
            assert _db().conversions.count_documents(
                {"user_id": VIP_ID, "op_id": op}) == 1
        finally:
            _restore_vip(snap)
