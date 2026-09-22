"""iter292 — Auditoría de monedas, tasas y convertidor (FX01–FX11 + riesgos).

Cobertura de los criterios de aceptación del informe d66806c:
- FX01: POST /admin/rates exige permiso `rates` y 2FA al cambiar un precio.
- FX02: barrido de saldos pequeños atómico — máx. un barrido y una comisión.
- FX03: tasas inválidas (0/-1/NaN/Inf) rechazadas; dato viejo NaN bloquea
  la conversión sin descontar.
- FX04: cotización ejecutable ÚNICA (rol) para convertidor y barrido; sin
  paridad USD=USDT inventada.
- FX05: destino inexistente/desactivado/no-convertible bloqueado en ambos
  caminos; origen desactivado SÍ liquida (decisión 22/09/2026).
- FX06: códigos únicos y con formato; identidad inmutable con referencias.
- FX07: normalización + par único (índice) + upsert atómico.
- FX08: el evento `rates_updated` solo lleva id/updated_at.
- FX09: registro durable + idempotencia por op_id.
- FX10: QUOTE_CHANGED cuando la tasa confirmada ya no está vigente.
- FX11: precisión por moneda, redondeo hacia abajo, resultado 0 → rechazo.
- Riesgo #1: venta < compra exige `allow_negative_margin` explícito.
- Riesgo #3: el barrido usa el USD COMBINADO (moderno + antiguo).
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN, \
    make_admin_totp
from tests.test_iter279_s01_s07 import _run

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"
EMP_ID = "user_test_employee01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _snapshot_vip():
    u = _db().users.find_one({"user_id": VIP_ID},
                             {"_id": 0, "vip_balances": 1, "vip_balance_usd": 1})
    return {"vip_balances": (u or {}).get("vip_balances") or {},
            "vip_balance_usd": float((u or {}).get("vip_balance_usd") or 0.0)}


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


def _mk_currency(code, type_="fiat", **kw):
    r = requests.post(f"{API}/admin/currencies", headers=_hdr(ADMIN_TOKEN),
                      json={"code": code, "name": f"IT292 {code}",
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
    db.rates.delete_many({"$or": [{"from_code": {"$regex": "^IT292"}},
                                  {"to_code": {"$regex": "^IT292"}},
                                  {"from_code": "USD", "to_code": "USDT"}]})
    db.currencies.delete_many({"code": {"$regex": "^IT292"}})
    db.conversions.delete_many({"user_id": VIP_ID,
                                "$or": [{"from_code": {"$regex": "^IT292"}},
                                        {"to_code": {"$regex": "^IT292"}},
                                        {"from_code": "USD"}]})


def _convert(body, tok=VIP_TOKEN):
    return requests.post(f"{API}/vip/convert", headers=_hdr(tok), json=body)


# ============================================================
# FX01 — permiso + 2FA en TODAS las vías de edición de tasas
# ============================================================

class TestFX01RateWritePermissions:
    def teardown_method(self, _):
        _cleanup_market()

    def test_employee_without_rates_permission_blocked_on_both_routes(self):
        db = _db()
        emp = db.users.find_one({"user_id": EMP_ID},
                                {"_id": 0, "allowed_permissions": 1}) or {}
        original = emp.get("allowed_permissions")
        db.users.update_one({"user_id": EMP_ID},
                            {"$set": {"allowed_permissions": ["orders"]}})
        try:
            body = {"from_code": "IT292PRM", "to_code": "USDT",
                    "rate_normal": 1, "rate_vip": 1}
            r_post = requests.post(f"{API}/admin/rates",
                                   headers=_hdr(EMPLOYEE_TOKEN), json=body)
            r_put = requests.put(f"{API}/admin/rates/some-id",
                                 headers=_hdr(EMPLOYEE_TOKEN), json=body)
            assert r_post.status_code == 403, r_post.text
            assert r_put.status_code == 403, r_put.text
        finally:
            if original is None:
                db.users.update_one({"user_id": EMP_ID},
                                    {"$unset": {"allowed_permissions": ""}})
            else:
                db.users.update_one({"user_id": EMP_ID},
                                    {"$set": {"allowed_permissions": original}})

    def test_post_on_existing_pair_requires_totp_stepup(self):
        _cleanup_market()
        _mk_currency("IT292TOT")
        created = _mk_rate("USDT", "IT292TOT", 100, 110)
        # sin código → 401 y el precio NO cambia
        r = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN),
                          json={"from_code": "USDT", "to_code": "IT292TOT",
                                "rate_normal": 700, "rate_vip": 705})
        assert r.status_code == 401, r.text
        row = _db().rates.find_one({"id": created["id"]}, {"_id": 0})
        assert row["rate_normal"] == 100, "el precio no cambia sin el código"
        # con código → 200 y actualiza el MISMO documento (par único)
        r = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN),
                          json={"from_code": "USDT", "to_code": "IT292TOT",
                                "rate_normal": 700, "rate_vip": 705,
                                "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        assert r.json()["id"] == created["id"]
        assert r.json()["rate_normal"] == 700


# ============================================================
# FX03 — validación de valores + dato viejo NaN
# ============================================================

class TestFX03RateValidation:
    def teardown_method(self, _):
        _cleanup_market()

    def test_invalid_rate_values_rejected(self):
        for v in [0, -1, "NaN", "Infinity", 1e13]:
            r = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN),
                              json={"from_code": "IT292BAD", "to_code": "USDT",
                                    "rate_normal": v, "rate_vip": v})
            assert r.status_code == 422, f"{v}: {r.status_code} {r.text}"

    def test_stale_nan_rate_blocks_conversion_without_debit(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292NAN")
            # dato viejo dañado plantado directo en la BD (esquiva el modelo)
            _db().rates.insert_one({
                "id": f"it292_{uuid.uuid4().hex[:8]}",
                "from_code": "USDT", "to_code": "IT292NAN",
                "rate_normal": float("nan"), "rate_vip": float("nan"),
                "updated_at": "2026-01-01T00:00:00+00:00"})
            _set_vip({"USDT": 100.0})
            r = _convert({"from_code": "USDT", "to_code": "IT292NAN",
                          "amount_from": 10})
            assert r.status_code == 400, r.text
            bal, _ = _vip_balances()
            assert bal["USDT"] == 100.0, "sin descuento ante tasa inválida"
            assert bal.get("IT292NAN") is None
        finally:
            _restore_vip(snap)


# ============================================================
# FX11 — precisión por moneda y redondeo hacia abajo
# ============================================================

class TestFX11Precision:
    def teardown_method(self, _):
        _cleanup_market()

    def test_zero_result_rejected_without_any_debit(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292F", "fiat")  # 4 decimales
            _mk_rate("USDT", "IT292F", 0.00001, 0.00001)
            _set_vip({"USDT": 10.0})
            r = _convert({"from_code": "USDT", "to_code": "IT292F",
                          "amount_from": 1})
            assert r.status_code == 400, r.text
            assert "unidad mínima" in str(r.json().get("detail"))
            bal, _ = _vip_balances()
            assert bal["USDT"] == 10.0, "nada descontado al acreditar cero"
        finally:
            _restore_vip(snap)

    def test_btc_round_trip_cannot_create_value(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292BTC", "crypto")  # 8 decimales
            _mk_rate("USDT", "IT292BTC", 0.00001, 0.00001)
            _set_vip({"USDT": 100.0})
            r1 = _convert({"from_code": "USDT", "to_code": "IT292BTC",
                           "amount_from": 5.01})
            assert r1.status_code == 200, r1.text
            assert r1.json()["amount_to"] == 0.0000501, \
                "cripto conserva su precisión exacta (no 0.0001)"
            r2 = _convert({"from_code": "IT292BTC", "to_code": "USDT",
                           "amount_from": 0.0000501})
            assert r2.status_code == 200, r2.text
            assert r2.json()["amount_to"] == 5.01
            bal, _ = _vip_balances()
            assert bal.get("IT292BTC", 0) == 0
            assert abs(bal["USDT"] - 99.98) < 1e-9, \
                f"ida y vuelta = solo comisiones (0.02): {bal['USDT']}"
        finally:
            _restore_vip(snap)


# ============================================================
# FX10 — cotización vinculada a la confirmación
# ============================================================

class TestFX10QuoteBinding:
    def teardown_method(self, _):
        _cleanup_market()

    def test_changed_rate_returns_409_without_executing(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292Q")
            _mk_rate("USDT", "IT292Q", 80, 80)  # la tasa vigente es 80
            _set_vip({"USDT": 100.0})
            # el cliente confirmó 100 (cotización vieja) → 409 sin mover nada
            r = _convert({"from_code": "USDT", "to_code": "IT292Q",
                          "amount_from": 10, "expected_rate": 100})
            assert r.status_code == 409, r.text
            det = r.json()["detail"]
            assert det["code"] == "QUOTE_CHANGED"
            assert det["current_rate"] == 80
            assert det["amount_to"] == 800
            bal, _ = _vip_balances()
            assert bal["USDT"] == 100.0 and not bal.get("IT292Q")
            # con la tasa vigente confirmada → ejecuta lo confirmado
            r = _convert({"from_code": "USDT", "to_code": "IT292Q",
                          "amount_from": 10, "expected_rate": 80})
            assert r.status_code == 200, r.text
            assert r.json()["amount_to"] == 800
        finally:
            _restore_vip(snap)


# ============================================================
# FX09 — registro durable + idempotencia
# ============================================================

class TestFX09DurableRecord:
    def teardown_method(self, _):
        _cleanup_market()

    def test_durable_record_and_op_id_idempotency(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292D")
            _mk_rate("USDT", "IT292D", 100, 100)
            _set_vip({"USDT": 100.0})
            op_id = f"it292-{uuid.uuid4().hex}"
            r = _convert({"from_code": "USDT", "to_code": "IT292D",
                          "amount_from": 10, "op_id": op_id})
            assert r.status_code == 200, r.text
            cid = r.json()["conversion_id"]
            row = _db().conversions.find_one({"id": cid}, {"_id": 0})
            assert row and row["status"] == "applied"
            assert row["amount_to"] == 1000 and row["rate"] == 100
            # reintento con el MISMO op_id → resultado guardado, sin doble débito
            r2 = _convert({"from_code": "USDT", "to_code": "IT292D",
                           "amount_from": 10, "op_id": op_id})
            assert r2.status_code == 200, r2.text
            assert r2.json().get("duplicate") is True
            assert r2.json()["conversion_id"] == cid
            bal, _ = _vip_balances()
            assert abs(bal["USDT"] - 89.99) < 1e-9, "un solo débito"
            assert bal["IT292D"] == 1000, "un solo crédito"
        finally:
            _restore_vip(snap)

    def test_history_survives_missing_audit_log(self):
        """FX09 — el historial se construye desde el registro durable: borrar
        la fila del audit_log (simula el log fallido) no borra la conversión
        del historial financiero."""
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292H")
            _mk_rate("USDT", "IT292H", 100, 100)
            _set_vip({"USDT": 100.0})
            r = _convert({"from_code": "USDT", "to_code": "IT292H",
                          "amount_from": 10})
            assert r.status_code == 200, r.text
            cid = r.json()["conversion_id"]
            _db().audit_log.delete_many({"details.conversion_id": cid})

            async def _f():
                from services.transactions import _fetch_conversions
                return await _fetch_conversions({}, "IT292H", VIP_ID)
            items = _run(_f)
            match = [it for it in items if it.get("ref_id") == cid]
            assert match, "la conversión sigue en el historial (fuente durable)"
            assert match[0]["amount_to"] == 1000
            assert match[0]["direction"] == "conversion"
        finally:
            _restore_vip(snap)


# ============================================================
# FX02 — barrido atómico: máx. un barrido y una comisión
# ============================================================

class TestFX02DustAtomic:
    def teardown_method(self, _):
        _cleanup_market()

    def test_concurrent_sweeps_charge_at_most_one_fee(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292CUP")
            _mk_rate("USDT", "IT292CUP", 100, 100)  # ejecutable: 1/100
            _set_vip({"USDT": 1.0, "IT292CUP": 300.0})

            def _sweep(_):
                return requests.post(f"{API}/vip/convert-dust",
                                     headers=_hdr(VIP_TOKEN), json={})
            with ThreadPoolExecutor(max_workers=2) as ex:
                results = list(ex.map(_sweep, range(2)))
            codes = sorted(r.status_code for r in results)
            assert codes[0] == 200 and codes[1] in (400, 409), codes
            ok = next(r for r in results if r.status_code == 200)
            assert len(ok.json()["items"]) == 1
            assert ok.json()["credited_usdt"] == 3.0
            bal, _ = _vip_balances()
            assert abs(bal["USDT"] - 3.99) < 1e-9, \
                f"una sola comisión: 1 - 0.01 + 3 = 3.99, got {bal['USDT']}"
            assert bal.get("IT292CUP", 0) == 0
            applied = _db().conversions.count_documents(
                {"user_id": VIP_ID, "from_code": "IT292CUP",
                 "status": "applied"})
            assert applied == 1, "exactamente un barrido registrado"
        finally:
            _restore_vip(snap)

    def test_dust_combines_legacy_and_modern_usd(self):
        """Riesgo-negocio #3 — selección, umbral y débito usan el USD
        COMBINADO (moderno + antiguo): nada queda a medias."""
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_rate("USD", "USDT", 1, 1)
            _set_vip({"USDT": 1.0, "USD": 2.0}, legacy_usd=2.0)
            pv = requests.get(f"{API}/vip/dust", headers=_hdr(VIP_TOKEN)).json()
            usd_item = next(i for i in pv["items"] if i["currency"] == "USD")
            assert usd_item["amount"] == 4.0, "monto COMBINADO (2 + 2)"
            assert usd_item["usdt_equivalent"] == 4.0
            r = requests.post(f"{API}/vip/convert-dust",
                              headers=_hdr(VIP_TOKEN), json={})
            assert r.status_code == 200, r.text
            bal, legacy = _vip_balances()
            assert legacy == 0.0, "saldo antiguo consumido"
            assert bal.get("USD", 0) == 0, "saldo moderno consumido"
            assert abs(bal["USDT"] - 4.99) < 1e-9
        finally:
            _restore_vip(snap)


# ============================================================
# FX04 — cotización ejecutable única (convertidor = barrido)
# ============================================================

class TestFX04UnifiedQuote:
    def teardown_method(self, _):
        _cleanup_market()

    def test_dust_applies_role_rate_like_converter(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_rate("USD", "USDT", 1, 1.1)  # VIP compra a 1.1
            _set_vip({"USDT": 1.0, "USD": 3.0})
            pv = requests.get(f"{API}/vip/dust", headers=_hdr(VIP_TOKEN)).json()
            usd = next(i for i in pv["items"] if i["currency"] == "USD")
            assert usd["usdt_equivalent"] == 3.3, \
                "el barrido usa la MISMA tasa de rol que el convertidor (VIP 1.1)"
            r = requests.post(f"{API}/vip/convert-dust",
                              headers=_hdr(VIP_TOKEN), json={})
            assert r.status_code == 200, r.text
            assert r.json()["credited_usdt"] == 3.3
        finally:
            _restore_vip(snap)

    def test_dust_never_invents_usd_usdt_parity(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _mk_currency("IT292EUR")
            _mk_currency("IT292USD")
            # solo existe IT292USD→IT292EUR: NO hay ruta ejecutable a USDT
            _mk_rate("IT292USD", "IT292EUR", 0.8, 0.85, sell=1)
            _set_vip({"USDT": 1.0, "IT292EUR": 2.0})
            pv = requests.get(f"{API}/vip/dust", headers=_hdr(VIP_TOKEN)).json()
            assert not any(i["currency"] == "IT292EUR" for i in pv["items"]), \
                "sin ruta ejecutable la moneda NO se ofrece"
            r = requests.post(f"{API}/vip/convert-dust",
                              headers=_hdr(VIP_TOKEN), json={})
            assert r.status_code == 400, "nada barrible → 400, saldo intacto"
            bal, _ = _vip_balances()
            assert bal["IT292EUR"] == 2.0 and bal["USDT"] == 1.0
        finally:
            _restore_vip(snap)


# ============================================================
# FX05 — guardas de catálogo en ambos caminos
# ============================================================

class TestFX05CatalogGuards:
    def teardown_method(self, _):
        _cleanup_market()

    def test_missing_and_inactive_destination_blocked(self):
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            _set_vip({"USDT": 10.0})
            # destino sin documento en el catálogo
            _mk_rate("USDT", "IT292GHOST", 100, 100)
            r = _convert({"from_code": "USDT", "to_code": "IT292GHOST",
                          "amount_from": 2})
            assert r.status_code == 400, r.text
            # destino desactivado
            cur = _mk_currency("IT292OFF")
            _mk_rate("USDT", "IT292OFF", 100, 100)
            requests.put(f"{API}/admin/currencies/{cur['id']}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"code": "IT292OFF", "name": "x",
                               "type": "fiat", "is_active": False})
            r = _convert({"from_code": "USDT", "to_code": "IT292OFF",
                          "amount_from": 2})
            assert r.status_code == 400, r.text
            bal, _ = _vip_balances()
            assert bal["USDT"] == 10.0, "nada descontado"
        finally:
            _restore_vip(snap)

    def test_inactive_origin_can_liquidate(self):
        """Decisión 22/09/2026 — moneda desactivada como ORIGEN sí liquida."""
        _cleanup_market()
        snap = _snapshot_vip()
        try:
            cur = _mk_currency("IT292OLD")
            _mk_rate("USDT", "IT292OLD", 100, 100)  # inversa: venta 100
            requests.put(f"{API}/admin/currencies/{cur['id']}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"code": "IT292OLD", "name": "x",
                               "type": "fiat", "is_active": False})
            _set_vip({"USDT": 1.0, "IT292OLD": 300.0})
            r = _convert({"from_code": "IT292OLD", "to_code": "USDT",
                          "amount_from": 300})
            assert r.status_code == 200, r.text
            assert r.json()["amount_to"] == 3.0
        finally:
            _restore_vip(snap)

    def test_dust_respects_usdt_convertible_flag(self):
        _cleanup_market()
        snap = _snapshot_vip()
        db = _db()
        usdt = db.currencies.find_one({"code": "USDT"}, {"_id": 0}) or {}
        original_flag = usdt.get("is_convertible_to", True)
        try:
            _mk_currency("IT292CUP")
            _mk_rate("USDT", "IT292CUP", 100, 100)
            _set_vip({"USDT": 1.0, "IT292CUP": 300.0})
            db.currencies.update_one({"code": "USDT"},
                                     {"$set": {"is_convertible_to": False}})
            pv = requests.get(f"{API}/vip/dust", headers=_hdr(VIP_TOKEN)).json()
            assert pv["can_convert"] is False and pv["reason"] == "usdt_blocked"
            r = requests.post(f"{API}/vip/convert-dust",
                              headers=_hdr(VIP_TOKEN), json={})
            assert r.status_code == 400, \
                "el barrido ya no esquiva el bloqueo de USDT como destino"
            bal, _ = _vip_balances()
            assert bal["IT292CUP"] == 300.0 and bal["USDT"] == 1.0
        finally:
            db.currencies.update_one(
                {"code": "USDT"},
                {"$set": {"is_convertible_to": original_flag}})
            _restore_vip(snap)


# ============================================================
# FX06 — identidad del catálogo de monedas
# ============================================================

class TestFX06CurrencyIdentity:
    def teardown_method(self, _):
        _cleanup_market()

    def test_duplicate_and_invalid_codes_rejected(self):
        _cleanup_market()
        _mk_currency("IT292DUP")
        r = requests.post(f"{API}/admin/currencies", headers=_hdr(ADMIN_TOKEN),
                          json={"code": " it292dup ", "name": "d",
                                "type": "fiat"})
        assert r.status_code == 409, "duplicado normalizado rechazado"
        for bad in ["", "   ", "A.B", "TOOLONGCODE13X", "X"]:
            r = requests.post(f"{API}/admin/currencies",
                              headers=_hdr(ADMIN_TOKEN),
                              json={"code": bad, "name": "x", "type": "fiat"})
            assert r.status_code == 422, f"{bad!r}: {r.status_code}"

    def test_code_immutable_with_references_and_delete_blocked(self):
        _cleanup_market()
        cur = _mk_currency("IT292REF")
        _mk_rate("USDT", "IT292REF", 100, 100)
        # renombrar con referencias → 409 (identidad monetaria inmutable)
        r = requests.put(f"{API}/admin/currencies/{cur['id']}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"code": "IT292REF2", "name": "x",
                               "type": "fiat"})
        assert r.status_code == 409, r.text
        # eliminar con referencias → 409 (desactivación controlada)
        r = requests.delete(f"{API}/admin/currencies/{cur['id']}",
                            headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 409, r.text
        # sin referencias → ambas operaciones proceden
        _db().rates.delete_many({"to_code": "IT292REF"})
        r = requests.put(f"{API}/admin/currencies/{cur['id']}",
                         headers=_hdr(ADMIN_TOKEN),
                         json={"code": "IT292REF2", "name": "x",
                               "type": "fiat"})
        assert r.status_code == 200, r.text
        r = requests.delete(f"{API}/admin/currencies/{cur['id']}",
                            headers=_hdr(ADMIN_TOKEN))
        assert r.status_code == 200, r.text


# ============================================================
# FX07 — normalización + unicidad del par
# ============================================================

class TestFX07RatePairUniqueness:
    def teardown_method(self, _):
        _cleanup_market()

    def test_codes_normalized_and_single_row_per_pair(self):
        _cleanup_market()
        r = _mk_rate(" it292nrm ", "it292dst ", 100, 100)
        assert r["from_code"] == "IT292NRM" and r["to_code"] == "IT292DST"
        # segundo POST del mismo par actualiza la MISMA fila
        r2 = _mk_rate("IT292NRM", "IT292DST", 200, 200)
        assert r2["id"] == r["id"]
        assert _db().rates.count_documents(
            {"from_code": "IT292NRM", "to_code": "IT292DST"}) == 1
        # origen = destino rechazado
        resp = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN),
                             json={"from_code": "IT292NRM",
                                   "to_code": "it292nrm",
                                   "rate_normal": 1, "rate_vip": 1})
        assert resp.status_code == 422

    def test_unique_index_installed(self):
        info = _db().rates.index_information()
        uniques = [v for v in info.values()
                   if v.get("unique") and v.get("key") == [("from_code", 1),
                                                           ("to_code", 1)]]
        assert uniques, f"índice único (from_code,to_code) instalado: {info}"


# ============================================================
# FX08 — el evento de tasas no filtra la tasa interna
# ============================================================

class TestFX08EventScrub:
    def teardown_method(self, _):
        _cleanup_market()

    def test_rates_updated_event_carries_only_id_and_version(self):
        async def _f():
            import services.live_bus as bus
            from routes.market import _persist_rate, ExchangeRateCreate
            sub = await bus.subscribe("it292-normal", "normal")
            try:
                payload = ExchangeRateCreate(
                    from_code="IT292EVT", to_code="USDT",
                    rate_normal=700, rate_vip=705, real_rate=750,
                    tiers=[{"min_amount": 200, "rate_normal": 705,
                            "rate_vip": 710, "real_rate": 760}])
                actor = {"user_id": "it292-admin", "role": "admin",
                         "name": "IT292", "email": "it292@test"}
                await _persist_rate(actor, payload, None)
                ev = await sub.queue.get()
                return ev
            finally:
                await bus.unsubscribe(sub)
        ev = _run(_f)
        assert ev["type"] == "rates_updated"
        assert set(ev["data"].keys()) == {"rate_id", "updated_at"}, \
            f"solo id/versión — sin documento interno: {ev['data']}"


# ============================================================
# Riesgo #1 — venta bajo compra exige decisión explícita
# ============================================================

class TestNegativeMarginPolicy:
    def teardown_method(self, _):
        _cleanup_market()

    def test_sell_below_buy_requires_explicit_flag(self):
        _cleanup_market()
        body = {"from_code": "IT292USD", "to_code": "IT292CUP",
                "rate_normal": 680, "rate_vip": 690, "rate_sell": 600,
                "totp_code": make_admin_totp()}
        r = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN),
                          json=body)
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "NEGATIVE_MARGIN"
        # con la decisión explícita → se guarda (y alerta a los admins)
        r = requests.post(f"{API}/admin/rates", headers=_hdr(ADMIN_TOKEN),
                          json={**body, "allow_negative_margin": True,
                                "totp_code": make_admin_totp()})
        assert r.status_code == 200, r.text
        assert r.json()["rate_sell"] == 600
