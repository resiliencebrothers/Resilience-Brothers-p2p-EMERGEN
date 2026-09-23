"""iter294 — Verificación f244eb0: RF01–RF06 (Monedas/Tasas/Convertidor).

RF04 · La suficiencia de saldo usa tolerancia RELATIVA (no eps absoluto):
tres barridos "stale" del mismo saldo BTC → 1 éxito + 2 conflictos, BTC
jamás negativo.
RF01 · Marcador ÚNICO por conversión; sellado por usuario+operación; el
registro embebido se compacta SIN expulsar marcadores pendientes (40+
operaciones posteriores no convierten en fallida una operación ejecutada).
RF02 · La idempotencia se resuelve ANTES de validar saldo/tasas: repetir el
mismo op_id devuelve el comprobante aunque el saldo quedara en cero; el
mismo op_id con otra intención → 409; op_id de un intento fallido → cerrado.
RF03 · El perdedor de una carrera de creación de tasa NO actualiza el precio
sin el mismo código 2FA que una edición normal.
RF06 · mypy (config de CI) verificado limpio manualmente — cubierto en CI.
"""
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
    u = _db().users.find_one({"user_id": VIP_ID},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1,
                              "recent_conversion_ids": 1})
    return {"vip_balances": (u or {}).get("vip_balances") or {},
            "vip_balance_usd": float((u or {}).get("vip_balance_usd") or 0.0),
            "recent_conversion_ids": (u or {}).get("recent_conversion_ids") or []}


def _restore_vip(snap):
    _db().users.update_one({"user_id": VIP_ID}, {"$set": snap})


def _set_vip(balances, legacy_usd=0.0):
    _db().users.update_one(
        {"user_id": VIP_ID},
        {"$set": {"vip_balances": balances, "vip_balance_usd": legacy_usd}})


def _vip_balances():
    u = _db().users.find_one({"user_id": VIP_ID},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    return dict((u or {}).get("vip_balances") or {}), \
        float((u or {}).get("vip_balance_usd") or 0.0)


def _vip_user_doc():
    u = _db().users.find_one({"user_id": VIP_ID}, {"_id": 0})
    assert u, "usuario VIP de prueba ausente"
    return u


def _mk_currency(code, type_="fiat", **kw):
    r = requests.post(f"{API}/admin/currencies", headers=_hdr(ADMIN_TOKEN),
                      json={"code": code, "name": f"IT294 {code}",
                            "type": type_, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_rate(from_code, to_code, normal, vip=None, sell=None, **kw):
    body = {"from_code": from_code, "to_code": to_code,
            "rate_normal": normal, "rate_vip": vip if vip is not None else normal,
            "totp_code": make_admin_totp(), **kw}
    if sell is not None:
        body["rate_sell"] = sell
    r = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup_market():
    db = _db()
    db.rates.delete_many({"$or": [{"from_code": {"$regex": "^IT294"}},
                                  {"to_code": {"$regex": "^IT294"}}]})
    db.currencies.delete_many({"code": {"$regex": "^IT294"}})
    db.conversions.delete_many({"user_id": VIP_ID,
                                "$or": [{"from_code": {"$regex": "^IT294"}},
                                        {"to_code": {"$regex": "^IT294"}},
                                        {"marker_id": {"$regex": "^it294"}}]})
    # Las filas de auditoría de corridas previas quedarían huérfanas (su
    # conversión durable ya no existe) y duplicarían el historial.
    db.audit_log.delete_many({"actor_id": VIP_ID,
                              "action": {"$in": ["vip.convert",
                                                 "vip.convert.dust"]},
                              "$or": [{"details.from_code":
                                       {"$regex": "^IT294"}},
                                      {"details.to_code":
                                       {"$regex": "^IT294"}}]})


def _convert(body, tok=VIP_TOKEN):
    return requests.post(f"{API}/vip/convert", headers=_hdr(tok), json=body)


def _call_route_with_stale_user(fn_call, stale_user):
    """Ejecuta una ruta de orders con `require_user` devolviendo SIEMPRE el
    mismo snapshot viejo del usuario — el punto exacto de la carrera
    'leyeron el saldo antes de escribir'."""
    async def _f():
        import routes.orders as om
        orig = om.require_user

        async def fake_ru(request):
            return dict(stale_user)

        om.require_user = fake_ru
        try:
            try:
                return 200, await fn_call(om)
            except om.HTTPException as ex:
                return ex.status_code, ex.detail
        finally:
            om.require_user = orig
    return _run(_f)


# ============================================================
# RF04 — suficiencia exacta: BTC jamás negativo
# ============================================================

class TestRF04SufficiencyEpsilon:
    def teardown_method(self, _):
        _cleanup_market()

    def test_triple_stale_sweep_one_success_two_conflicts(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT294BT", "crypto")
            _mk_rate("USDT", "IT294BT", 0.00001, 0.00001)
            # 50 satoshis ≈ 0.05 USDT (dust) + 1 USDT para la comisión.
            _set_vip({"USDT": 1.0, "IT294BT": 0.0000005})
            stale = _vip_user_doc()
            codes = []
            for _ in range(3):
                code, _body = _call_route_with_stale_user(
                    lambda om: om.vip_convert_dust(None, None), stale)
                codes.append(code)
            assert codes == [200, 409, 409], \
                f"un solo barrido y dos conflictos, no {codes}"
            bal, _ = _vip_balances()
            assert bal.get("IT294BT", 0.0) >= 0.0, "BTC jamás negativo"
            assert bal.get("IT294BT", 0.0) == 0.0
            assert abs(bal["USDT"] - 1.04) < 1e-9, \
                f"una sola comisión: 1 + 0.05 − 0.01 = 1.04, no {bal['USDT']}"
            applied = list(_db().conversions.find(
                {"user_id": VIP_ID, "from_code": "IT294BT",
                 "status": "applied"}))
            assert len(applied) == 1, "exactamente un barrido aplicado"
        finally:
            _restore_vip(snap)

    def test_exact_balance_sweep_still_works(self):
        """La tolerancia relativa no rompe el barrido legítimo: un saldo
        exacto (con ruido float típico) se barre a la primera."""
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT294F")
            _mk_rate("USDT", "IT294F", 100, 100)
            # 0.1+0.2 = 0.30000000000000004 → 300.00000000000006 escalado.
            _set_vip({"USDT": 1.0, "IT294F": (0.1 + 0.2) * 1000})
            r = requests.post(f"{API}/vip/convert-dust", headers=_hdr(VIP_TOKEN),
                              json={})
            assert r.status_code == 200, r.text
            bal, _ = _vip_balances()
            assert bal.get("IT294F", 0.0) <= 1e-9
        finally:
            _restore_vip(snap)


# ============================================================
# RF01 — marcador único, sellado acotado y compactación segura
# ============================================================

class TestRF01Markers:
    def teardown_method(self, _):
        _cleanup_market()

    def test_marker_unique_nonempty_per_conversion(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT294M")
            _mk_rate("USDT", "IT294M", 100, 100)
            _set_vip({"USDT": 100.0})
            r = _convert({"from_code": "USDT", "to_code": "IT294M",
                          "amount_from": 10})
            assert r.status_code == 200, r.text
            doc = _db().conversions.find_one({"id": r.json()["conversion_id"]})
            assert doc["marker_id"], "marcador jamás vacío"
            assert doc["marker_id"].startswith("cmk_")
        finally:
            _restore_vip(snap)

    def test_race_loser_marked_failed_not_applied(self):
        """Dos conversiones de 8 USDT compiten sobre 10: la perdedora queda
        `failed` — el historial NO informa 1.600 CUP por marcador compartido."""
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT294R")
            _mk_rate("USDT", "IT294R", 100, 100)
            _set_vip({"USDT": 10.0})
            stale = _vip_user_doc()

            def _mk_call(om):
                payload = om.VipConvertPayload(from_code="USDT",
                                               to_code="IT294R",
                                               amount_from=8)
                return om.vip_convert(payload, None)

            c1, _ = _call_route_with_stale_user(_mk_call, stale)
            c2, _ = _call_route_with_stale_user(_mk_call, stale)
            assert sorted([c1, c2]) == [200, 409]
            rows = list(_db().conversions.find(
                {"user_id": VIP_ID, "to_code": "IT294R"}))
            statuses = sorted(r["status"] for r in rows)
            assert statuses == ["applied", "failed"], statuses
            bal, _ = _vip_balances()
            assert bal["IT294R"] == 800, "un solo crédito de 800"

            async def _f():
                from services.transactions import _fetch_conversions
                return await _fetch_conversions({}, "IT294R", VIP_ID)
            items = _run(_f)
            total = sum(i["amount_to"] for i in items
                        if i.get("currency") == "IT294R"
                        or i.get("to_code") == "IT294R")
            assert total == 800, f"el historial coincide con lo real: {total}"
        finally:
            _restore_vip(snap)

    def test_seal_failure_healed_as_applied_once(self):
        """Dinero movido + sello caído: el sanador resuelve `applied` por el
        marcador durable y la conversión reaparece UNA sola vez."""
        _cleanup_market()
        snap = _snapshot_vip()
        marker = f"it294_seal_{uuid.uuid4().hex[:8]}"
        cid = f"conv_it294_{uuid.uuid4().hex[:8]}"
        try:
            _db().conversions.insert_one({
                "id": cid, "user_id": VIP_ID, "user_name": "VIP",
                "user_email": "", "kind": "convert", "from_code": "USDT",
                "to_code": "IT294S", "amount_from": 10.0, "amount_to": 1000.0,
                "rate": 100.0, "usdt_fee": 0.01, "amount_from_usdt": 10.0,
                "marker_id": marker, "status": "applying",
                "created_at": "2020-01-01T00:00:00+00:00"})
            _db().users.update_one({"user_id": VIP_ID},
                                   {"$push": {"recent_conversion_ids": marker}})

            async def _f():
                from services.conversions import heal_pending_conversions
                await heal_pending_conversions(max_age_seconds=0)
                await heal_pending_conversions(max_age_seconds=0)
            _run(_f)
            doc = _db().conversions.find_one({"id": cid})
            assert doc["status"] == "applied"
        finally:
            _db().conversions.delete_many({"id": cid})
            _restore_vip(snap)

    def test_40_plus_ops_cannot_fail_pending_marker(self):
        """El marcador de una operación EJECUTADA (sello pendiente) sobrevive
        a 45 operaciones posteriores: la compactación solo retira resueltos."""
        _cleanup_market()
        snap = _snapshot_vip()
        marker = f"it294_pend_{uuid.uuid4().hex[:8]}"
        cid = f"conv_it294_{uuid.uuid4().hex[:8]}"
        resolved = [f"it294_res_{i}_{uuid.uuid4().hex[:6]}" for i in range(45)]
        try:
            _db().users.update_one(
                {"user_id": VIP_ID},
                {"$set": {"recent_conversion_ids": [marker] + resolved}})
            _db().conversions.insert_one({
                "id": cid, "user_id": VIP_ID, "user_name": "VIP",
                "user_email": "", "kind": "dust", "from_code": "IT294P",
                "to_code": "USDT", "amount_from": 300.0, "amount_to": 3.0,
                "rate": 0.01, "usdt_fee": 0.01, "amount_from_usdt": 3.0,
                "marker_id": marker, "status": "applying",
                "created_at": "2020-01-01T00:00:00+00:00"})

            async def _compact_twice():
                from services.conversions import compact_conversion_markers
                await compact_conversion_markers()
                await compact_conversion_markers()
            _run(_compact_twice)
            u = _db().users.find_one({"user_id": VIP_ID},
                                     {"_id": 0, "recent_conversion_ids": 1})
            arr = u.get("recent_conversion_ids") or []
            assert marker in arr, \
                "la prueba durable de una operación pendiente JAMÁS se expulsa"
            assert len(arr) < 46, "la compactación sí retira resueltos"

            async def _heal():
                from services.conversions import heal_pending_conversions
                await heal_pending_conversions(max_age_seconds=0)
            _run(_heal)
            doc = _db().conversions.find_one({"id": cid})
            assert doc["status"] == "applied", \
                "40+ operaciones posteriores no la convierten en fallida"
        finally:
            _db().conversions.delete_many({"id": cid})
            _restore_vip(snap)

    def test_mark_conversions_scoped_by_user(self):
        """El sellado con marcador vacío no toca nada; con marcador ajeno
        (otro usuario) tampoco."""
        other = f"conv_it294_{uuid.uuid4().hex[:8]}"
        try:
            _db().conversions.insert_one({
                "id": other, "user_id": "otro_usuario", "marker_id": "it294_mk",
                "status": "applying", "created_at": "2020-01-01T00:00:00+00:00"})

            async def _f():
                from services.conversions import mark_conversions
                await mark_conversions(VIP_ID, "", "applied")
                await mark_conversions(VIP_ID, "it294_mk", "applied")
            _run(_f)
            doc = _db().conversions.find_one({"id": other})
            assert doc["status"] == "applying", \
                "el sellado de un usuario jamás alcanza registros ajenos"
        finally:
            _db().conversions.delete_many({"id": other})


# ============================================================
# RF02 — reintento recupera el comprobante, jamás re-ejecuta
# ============================================================

class TestRF02StableRetry:
    def teardown_method(self, _):
        _cleanup_market()

    def test_retry_after_drained_balance_returns_receipt(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT294X")
            _mk_rate("USDT", "IT294X", 100, 100)
            _set_vip({"USDT": 10.01})
            op = f"it294op_{uuid.uuid4().hex[:12]}"
            body = {"from_code": "USDT", "to_code": "IT294X",
                    "amount_from": 10, "op_id": op}
            r1 = _convert(body)
            assert r1.status_code == 200, r1.text
            bal, _ = _vip_balances()
            assert abs(bal["USDT"]) < 1e-9, "saldo agotado tras la conversión"
            # La respuesta se "perdió": el reintento usa el MISMO op_id y
            # recupera el comprobante aunque el saldo esté en cero.
            r2 = _convert(body)
            assert r2.status_code == 200, \
                f"debe devolver el comprobante, no {r2.status_code}: {r2.text}"
            assert r2.json().get("duplicate") is True
            assert r2.json()["conversion_id"] == r1.json()["conversion_id"]
            bal2, _ = _vip_balances()
            assert abs(bal2["USDT"]) < 1e-9 and bal2["IT294X"] == 1000, \
                "un solo débito, una sola comisión, un solo crédito"
        finally:
            _restore_vip(snap)

    def test_retry_after_rate_change_returns_receipt(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT294Y")
            rate = _mk_rate("USDT", "IT294Y", 100, 100)
            _set_vip({"USDT": 100.0})
            op = f"it294op_{uuid.uuid4().hex[:12]}"
            body = {"from_code": "USDT", "to_code": "IT294Y",
                    "amount_from": 10, "op_id": op}
            r1 = _convert(body)
            assert r1.status_code == 200, r1.text
            # La tasa cambia DESPUÉS de la operación original.
            requests.put(f"{API}/admin/rates/{rate['id']}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"from_code": "USDT", "to_code": "IT294Y",
                               "rate_normal": 80, "rate_vip": 80,
                               "totp_code": make_admin_totp()})
            r2 = _convert(body)
            assert r2.status_code == 200 and r2.json().get("duplicate") is True
            assert r2.json()["rate"] == 100, "el comprobante original, no la tasa nueva"
        finally:
            _restore_vip(snap)

    def test_same_op_id_different_intent_409(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT294Z")
            _mk_rate("USDT", "IT294Z", 100, 100)
            _set_vip({"USDT": 100.0})
            op = f"it294op_{uuid.uuid4().hex[:12]}"
            r1 = _convert({"from_code": "USDT", "to_code": "IT294Z",
                           "amount_from": 10, "op_id": op})
            assert r1.status_code == 200, r1.text
            r2 = _convert({"from_code": "USDT", "to_code": "IT294Z",
                           "amount_from": 5, "op_id": op})
            assert r2.status_code == 409, r2.text
            assert r2.json()["detail"]["code"] == "OP_ID_REUSED"
        finally:
            _restore_vip(snap)

    def test_failed_op_id_is_closed(self):
        _cleanup_market()
        snap = _snapshot_vip()
        op = f"it294op_{uuid.uuid4().hex[:12]}"
        cid = f"conv_it294_{uuid.uuid4().hex[:8]}"
        try:
            _mk_currency("IT294W")
            _mk_rate("USDT", "IT294W", 100, 100)
            _set_vip({"USDT": 100.0})
            _db().conversions.insert_one({
                "id": cid, "user_id": VIP_ID, "op_id": op,
                "kind": "convert", "from_code": "USDT", "to_code": "IT294W",
                "amount_from": 10.0, "amount_to": 1000.0, "rate": 100.0,
                "usdt_fee": 0.01, "amount_from_usdt": 10.0,
                "marker_id": f"it294_{uuid.uuid4().hex[:6]}",
                "status": "failed", "created_at": "2020-01-01T00:00:00+00:00"})
            r = _convert({"from_code": "USDT", "to_code": "IT294W",
                          "amount_from": 10, "op_id": op})
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "OP_ID_CLOSED"
            bal, _ = _vip_balances()
            assert bal["USDT"] == 100.0, "nada se movió"
        finally:
            _db().conversions.delete_many({"id": cid})
            _restore_vip(snap)


# ============================================================
# RF03 — la carrera de creación no salta el 2FA
# ============================================================

class TestRF03CreateRaceTotp:
    def teardown_method(self, _):
        _cleanup_market()

    def _persist_as_creation(self, payload_kw):
        """Ejecuta la rama REAL del conflicto de unicidad: _persist_rate con
        existing=None cuando la fila ya existe (el perdedor de la carrera)."""
        async def _f():
            import routes.market as mk
            actor = _db().users.find_one({"user_id": "user_test_admin01"},
                                         {"_id": 0})
            payload = mk.ExchangeRateCreate(**payload_kw)
            try:
                return 200, await mk._persist_rate(actor, payload, None)
            except mk.HTTPException as ex:
                return ex.status_code, ex.detail
        return _run(_f)

    def test_race_loser_without_code_cannot_change_price(self):
        _cleanup_market()
        _mk_currency("IT294T")
        _mk_rate("USDT", "IT294T", 100, 100)  # ganador de la carrera
        code, detail = self._persist_as_creation({
            "from_code": "USDT", "to_code": "IT294T",
            "rate_normal": 200, "rate_vip": 200})
        assert code in (401, 412), \
            f"sin código 2FA el perdedor no puede cambiar el precio: {code} {detail}"
        row = _db().rates.find_one({"from_code": "USDT", "to_code": "IT294T"})
        assert row["rate_normal"] == 100, "el precio recién creado no cambió"

    def test_race_loser_with_valid_code_updates(self):
        _cleanup_market()
        _mk_currency("IT294U")
        _mk_rate("USDT", "IT294U", 100, 100)
        code, _ = self._persist_as_creation({
            "from_code": "USDT", "to_code": "IT294U",
            "rate_normal": 200, "rate_vip": 200,
            "totp_code": make_admin_totp()})
        assert code == 200
        row = _db().rates.find_one({"from_code": "USDT", "to_code": "IT294U"})
        assert row["rate_normal"] == 200

    def test_race_loser_same_values_needs_no_code(self):
        _cleanup_market()
        _mk_currency("IT294V")
        _mk_rate("USDT", "IT294V", 100, 100)
        code, _ = self._persist_as_creation({
            "from_code": "USDT", "to_code": "IT294V",
            "rate_normal": 100, "rate_vip": 100})
        assert code == 200, "valores idénticos = sin cambio de precio"
