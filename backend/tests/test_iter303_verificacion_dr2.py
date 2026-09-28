"""iter303 — Verificación de Depósitos y Retiros (informe 623deba):
residuales DR09 (crítica), DR02 (alta), DE01 (media) y DR10 (baja).

DR09 v2  El vencimiento de la intención de cancelación ya no libera una
         decisión de reembolso COMPROMETIDA: la toma de una intención antigua
         y la limpieza del perdedor comprueban el reembolso persistido y
         escalan la intención a `committed` (jamás robable/liberable) — la
         entrega no puede sellarse mientras el reembolso siga vivo.
DR02 v2  (A) Las reservas de evidencia con el formato anterior (clave
         terminada en el importe) se MIGRAN a la clave canónica sin liberar
         la identidad consumida. (B) Una reanudación con OTRO ID de
         movimiento hace una transición controlada y exclusiva de la reserva:
         depósito, reserva e ID son siempre la misma identidad.
DE01 v2  El mínimo de 1 USDT se valida con aritmética decimal SIN redondeo
         de presentación (0.99995 ya no «se vuelve» 1) y se protege TAMBIÉN
         al confirmar: sin tasa resoluble o bajo el mínimo → 409.
DR10     El aviso administrativo «Nuevo retiro» se invoca en TODOS los
         métodos (la importación condicional causaba UnboundLocalError).
"""
import asyncio
import os
import types
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from conftest import BASE_URL, ADMIN_TOKEN as ADMIN

API = f"{BASE_URL}/api"
MARK = "iter303"

CLIA_ID = "user_test_cli303a"
CLIA_TOKEN = f"test_session_{uuid.uuid4().hex}"
COURIER_ID = "user_test_cou303"
COURIER_TOKEN = f"test_session_{uuid.uuid4().hex}"

CRYPTO_ID = "TU3"   # cripto CON tasa identidad (1 TU3 = 1 USDT)
CRYPTO_NR = "TQ8"   # cripto SIN tasa inicial (se configura dentro del test)
FIAT_TR = "TF3"     # fiat de prueba con método transferencia
TRC20_ADDR = "TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


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


def _now():
    return datetime.now(timezone.utc).isoformat()


def _old(minutes=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _bal(uid, code):
    u = _db().users.find_one({"user_id": uid},
                             {"vip_balances": 1, "vip_balance_usd": 1}) or {}
    total = float((u.get("vip_balances") or {}).get(code) or 0.0)
    if code == "USD":
        total += float(u.get("vip_balance_usd") or 0.0)
    return total


def _set_bal(uid, code, amount):
    sets = {f"vip_balances.{code}": float(amount)}
    if code == "USD":
        sets["vip_balance_usd"] = 0.0
    _db().users.update_one({"user_id": uid}, {"$set": sets})


def setup_module():
    db = _db()
    for uid, tok, extra in (
        (CLIA_ID, CLIA_TOKEN, {"role": "vip"}),
        (COURIER_ID, COURIER_TOKEN, {"role": "vip", "is_courier": True}),
    ):
        db.users.update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "email": f"{uid}@test.com", "name": uid,
                      "vip_balances": {}, "applied_credit_ops": [], **extra}},
            upsert=True)
        db.user_sessions.update_one(
            {"session_token": tok},
            {"$set": {"session_token": tok, "user_id": uid,
                      "expires_at": "2099-01-01T00:00:00+00:00"}},
            upsert=True)
    for code, ctype, methods in ((CRYPTO_ID, "crypto", ["crypto"]),
                                 (CRYPTO_NR, "crypto", ["crypto"]),
                                 (FIAT_TR, "fiat", ["transfer", "cash"])):
        db.currencies.update_one(
            {"code": code},
            {"$set": {"code": code, "name": f"Test {code}", "type": ctype,
                      "is_active": True, "delivery_methods": methods}},
            upsert=True)
    db.rates.update_one(
        {"from_code": CRYPTO_ID, "to_code": "USDT"},
        {"$set": {"from_code": CRYPTO_ID, "to_code": "USDT",
                  "rate_normal": 1.0, "rate_vip": 1.0, "real_rate": 1.0}},
        upsert=True)
    _cleanup_data()


def teardown_module():
    db = _db()
    db.users.delete_many({"user_id": {"$in": [CLIA_ID, COURIER_ID]}})
    db.user_sessions.delete_many({"session_token": {
        "$in": [CLIA_TOKEN, COURIER_TOKEN]}})
    db.currencies.delete_many({"code": {"$in": [CRYPTO_ID, CRYPTO_NR,
                                                FIAT_TR]}})
    db.rates.delete_many({"from_code": {"$in": [CRYPTO_ID, CRYPTO_NR]}})
    _cleanup_data()


def _cleanup_data():
    db = _db()
    db.withdrawals.delete_many({"id": {"$regex": f"^wd_{MARK}"}})
    db.withdrawals.delete_many({"user_id": CLIA_ID})
    db.deposits.delete_many({"id": {"$regex": f"^dep_{MARK}"}})
    db.deposits.delete_many({"user_id": CLIA_ID})
    db.deposits.delete_many({"tx_hash": {"$regex": MARK}})
    db.deliveries.delete_many({"id": {"$regex": f"^dv_{MARK}"}})
    db.crypto_evidence_claims.delete_many({"tx_hash": {"$regex": MARK}})
    db.credit_ops.delete_many({"op_id": {"$regex": MARK}})


def _mk_withdrawal(wid, user_id=CLIA_ID, amount=100.0, currency="USD",
                   method="cash", status="pending", **extra):
    doc = {
        "id": wid, "user_id": user_id, "user_email": f"{user_id}@test.com",
        "user_name": user_id, "amount_usd": float(amount),
        "currency": currency, "method": method, "details": "detalle prueba",
        "status": status, "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().withdrawals.insert_one(dict(doc))
    return doc


def _mk_delivery(dvid, wid, status="arrived", courier=COURIER_ID, **extra):
    doc = {
        "id": dvid, "kind": "withdrawal", "ref_id": wid, "status": status,
        "courier_id": courier, "courier_name": courier,
        "user_id": CLIA_ID, "client_name": "Cliente Prueba",
        "amount_label": "100 USD", "timeline": [],
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deliveries.insert_one(dict(doc))
    return doc


def _mk_deposit(dep_id, user_id=CLIA_ID, amount=100.0, currency="USDT",
                method="crypto", status="pending", **extra):
    doc = {
        "id": dep_id, "user_id": user_id, "user_email": f"{user_id}@test.com",
        "user_name": user_id, "user_role": "vip", "currency": currency,
        "amount": float(amount), "method": method, "cash_mode": None,
        "network": None, "usdt_equivalent": None, "account_holder": None,
        "tx_hash": None, "proof_url": None, "note": None, "status": status,
        "admin_note": None, "reviewed_at": None, "reviewed_by": None,
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deposits.insert_one(dict(doc))
    return doc


def _confirm(dep_id, body=None):
    return requests.post(f"{API}/admin/deposits/{dep_id}/confirm",
                         headers=_h(ADMIN), json=body or {})


def _cancel(wid, token=CLIA_TOKEN):
    return requests.post(f"{API}/vip/withdrawals/{wid}/cancel",
                         headers=_h(token))


def _seal_delivered(dvid, token=COURIER_TOKEN):
    return requests.post(f"{API}/courier/deliveries/{dvid}/status",
                         headers=_h(token), json={"status": "delivered"})


# ---------------------------------------------------------------------------
# DR09 v2 — la intención vencida no libera un reembolso comprometido
# ---------------------------------------------------------------------------
class TestDR09ExpiredCancelIntent:
    def test_expired_intent_over_committed_refund_never_stolen(self):
        """Reproducción expired_cancel_intent: la primera cancelación reservó
        la intención, PERSISTIÓ el reembolso (cancelled + credit_pending) y
        quedó pausada antes de acreditar; su intención tiene >120s. El
        reintento NO puede tomarla ni liberarla: la escala a comprometida y
        la entrega queda impedida — resultado «reembolso con entrega
        impedida», jamás ambos."""
        from services.credit_markers import pending_marker
        wid = f"wd_{MARK}_x1"
        marker = pending_marker(CLIA_ID, "USD", 100.0,
                                f"withdrawal-cancel-refund-{MARK}")
        _mk_withdrawal(wid, status="cancelled", balance_refunded=True,
                       credit_pending=marker, cancelled_at=_now())
        dv = _mk_delivery(f"dv_{MARK}_x1", wid, status="arrived",
                          origin_cancel_intent={"at": _old(3), "by": CLIA_ID,
                                                "token": "tokFIRST"})
        _set_bal(CLIA_ID, "USD", 0)
        # paso 4 del auditor: el reintento considera la intención antigua
        r = _cancel(wid)
        assert r.status_code == 409, r.text
        fresh = _db().deliveries.find_one({"id": dv["id"]})
        intent = fresh.get("origin_cancel_intent") or {}
        assert intent.get("token") == "tokFIRST", \
            "la intención del reembolso comprometido jamás se roba"
        assert intent.get("committed") is True, \
            "la intención debe escalar a comprometida"
        # paso 5: el mensajero ya NO puede sellar la entrega — la regla N03
        # detecta el origen cancelado y cierra la entrega coherentemente.
        r2 = _seal_delivered(dv["id"])
        assert r2.status_code == 409, r2.text
        sealed = _db().deliveries.find_one({"id": dv["id"]})
        assert sealed["status"] != "delivered", \
            "jamás entrega sellada con reembolso comprometido"
        assert not sealed.get("pin_verified")
        # un segundo reintento de cancelación tampoco acredita nada
        r3 = _cancel(wid)
        assert r3.status_code == 409
        assert _bal(CLIA_ID, "USD") == 0.0
        # paso 6: la primera cancelación reanuda y acredita UNA sola vez;
        # la coordinación cierra la entrega de forma coherente.

        async def finish():
            from services.credit_recovery import apply_and_clear
            from services.deliveries import handle_origin_rejected
            await apply_and_clear("withdrawals", wid, marker)
            await handle_origin_rejected("withdrawal", wid,
                                         actor_id=CLIA_ID,
                                         note="cancelación reanudada")
        _run(finish)
        assert _bal(CLIA_ID, "USD") == 100.0, "reembolso único de 100"
        final = _db().deliveries.find_one({"id": dv["id"]})
        assert final["status"] == "cancelled", \
            "la entrega cierra cancelada, jamás delivered con reembolso"

    def test_losing_retry_escalates_instead_of_releasing(self):
        """Si un robo+liberación previos dejaron la entrega SIN intención con
        el reembolso ya comprometido, el reintento que pierde el claim del
        retiro NO libera su intención nueva: la escala a comprometida y el
        sello del mensajero sigue impedido."""
        from services.credit_markers import pending_marker
        wid = f"wd_{MARK}_x2"
        marker = pending_marker(CLIA_ID, "USD", 100.0,
                                f"withdrawal-cancel-refund-{MARK}")
        _mk_withdrawal(wid, status="cancelled", balance_refunded=True,
                       credit_pending=marker, cancelled_at=_now())
        dv = _mk_delivery(f"dv_{MARK}_x2", wid, status="arrived")  # sin intención
        _set_bal(CLIA_ID, "USD", 0)
        r = _cancel(wid)
        assert r.status_code == 409, r.text
        fresh = _db().deliveries.find_one({"id": dv["id"]})
        intent = fresh.get("origin_cancel_intent") or {}
        assert intent and intent.get("committed") is True, \
            "el perdedor escala su intención (no la libera) ante un reembolso comprometido"
        r2 = _seal_delivered(dv["id"])
        assert r2.status_code == 409, r2.text
        sealed = _db().deliveries.find_one({"id": dv["id"]})
        assert sealed["status"] != "delivered", \
            "jamás entrega sellada con reembolso comprometido"
        assert _bal(CLIA_ID, "USD") == 0.0, "el reintento jamás acredita"

    def test_true_orphan_intent_still_recovered_when_pending(self):
        """Recuperación legítima conservada: una intención >120s de un intento
        muerto sobre un retiro AÚN pendiente (sin reembolso persistido) se
        retoma y la cancelación completa con reembolso único."""
        wid = f"wd_{MARK}_x3"
        _mk_withdrawal(wid)  # pending, sin decisión persistida
        _mk_delivery(f"dv_{MARK}_x3", wid, status="accepted",
                     origin_cancel_intent={"at": _old(10), "by": CLIA_ID,
                                           "token": "tokDEAD"})
        _set_bal(CLIA_ID, "USD", 0)
        r = _cancel(wid)
        assert r.status_code == 200, r.text
        assert _bal(CLIA_ID, "USD") == 100.0
        assert _db().withdrawals.find_one({"id": wid})["status"] == "cancelled"
        assert _db().deliveries.find_one(
            {"id": f"dv_{MARK}_x3"})["status"] == "cancelled"


# ---------------------------------------------------------------------------
# DR02 v2 — migración de reservas legado + identidad inmutable al reanudar
# ---------------------------------------------------------------------------
class TestDR02EvidenceMigration:
    def _migrate(self):
        async def mig():
            import routes.deposits as depmod
            depmod._claims_index_ready = False
            await depmod._ensure_evidence_claims_index()
        _run(mig)

    def test_legacy_format_claim_migrates_and_blocks_recredit(self):
        """Reproducción evidence_migration: una reserva con el formato
        anterior (clave terminada en el importe) se migra a la clave canónica
        — volver a declarar el mismo movimiento recibe 409, jamás 100→200."""
        h = f"{MARK}hash_lga"
        dep_a = _mk_deposit(f"dep_{MARK}_l1", amount=100.0, tx_hash=h,
                            network="BEP20", status="confirmed")
        _db().crypto_evidence_claims.insert_one({
            "claim_key": f"BEP20|{h}|USDT|100.00000000",
            "deposit_id": dep_a["id"], "user_id": CLIA_ID,
            "network": "BEP20", "tx_hash": h, "currency": "USDT",
            "amount": 100.0, "at": _old(60)})
        _set_bal(CLIA_ID, "USDT", 100.0)  # abono histórico ya aplicado
        self._migrate()
        row = _db().crypto_evidence_claims.find_one({"deposit_id": dep_a["id"]})
        assert row["claim_key"] == f"BEP20|{h}|USDT|", row
        assert row["legacy_key"] == f"BEP20|{h}|USDT|100.00000000"
        d_new = _mk_deposit(f"dep_{MARK}_l2", amount=100.0, tx_hash=h,
                            network="BEP20")
        r = _confirm(d_new["id"])
        assert r.status_code == 409, r.text
        assert _bal(CLIA_ID, "USDT") == 100.0, "jamás pasa de 100 a 200"
        assert _db().deposits.find_one({"id": d_new["id"]})["status"] == "pending"

    def test_legacy_double_pair_migrates_without_freeing_identity(self):
        """Dos reservas legado con la MISMA identidad (doble abono antiguo):
        la primera conserva la clave canónica y la otra queda marcada como
        duplicado legado — la identidad no se libera y una nueva declaración
        recibe 409."""
        h = f"{MARK}hash_lgb"
        a1 = _mk_deposit(f"dep_{MARK}_l3", amount=100.0, tx_hash=h,
                         network="BEP20", status="confirmed")
        a2 = _mk_deposit(f"dep_{MARK}_l4", amount=99.0, tx_hash=h,
                         network="BEP20", status="confirmed")
        for dep, amt in ((a1, "100.00000000"), (a2, "99.00000000")):
            _db().crypto_evidence_claims.insert_one({
                "claim_key": f"BEP20|{h}|USDT|{amt}",
                "deposit_id": dep["id"], "user_id": CLIA_ID,
                "network": "BEP20", "tx_hash": h, "currency": "USDT",
                "amount": float(amt), "at": _old(60)})
        _set_bal(CLIA_ID, "USDT", 199.0)
        self._migrate()
        keys = sorted(r["claim_key"] for r in
                      _db().crypto_evidence_claims.find({"tx_hash": h}))
        canonical = f"BEP20|{h}|USDT|"
        assert canonical in keys, keys
        assert any(k.startswith(f"{canonical}|legacy-dup:") for k in keys), keys
        d_new = _mk_deposit(f"dep_{MARK}_l5", amount=100.0, tx_hash=h,
                            network="BEP20")
        r = _confirm(d_new["id"])
        assert r.status_code == 409, r.text
        assert _bal(CLIA_ID, "USDT") == 199.0

    def test_resumption_with_new_movement_id_moves_claim_exclusively(self):
        """Reproducción evidence_resumption_identity: reanudar con OTRO ID de
        movimiento actualiza la reserva de forma coherente y EXCLUSIVA —
        depósito, reserva e ID quedan como la misma identidad y nadie más
        puede confirmar ese movimiento."""
        h = f"{MARK}hash_res"
        dep_a = _mk_deposit(f"dep_{MARK}_r1", amount=100.0, tx_hash=h,
                            network="BEP20")
        # reserva del intento interrumpido (identidad log:0), depósito pendiente
        _db().crypto_evidence_claims.insert_one({
            "claim_key": f"BEP20|{h}|USDT|log:0", "deposit_id": dep_a["id"],
            "user_id": CLIA_ID, "network": "BEP20", "tx_hash": h,
            "currency": "USDT", "amount": 100.0, "movement_id": "log:0",
            "at": _now()})
        _set_bal(CLIA_ID, "USDT", 0)
        r = _confirm(dep_a["id"], {"evidence_movement_id": "log:1"})
        assert r.status_code == 200, r.text
        fresh = _db().deposits.find_one({"id": dep_a["id"]})
        assert fresh["evidence_movement_id"] == "log:1"
        row = _db().crypto_evidence_claims.find_one(
            {"deposit_id": dep_a["id"], "superseded": {"$ne": True}})
        assert row["claim_key"] == f"BEP20|{h}|USDT|log:1", \
            "la reserva vigente migró a la identidad realmente confirmada"
        assert row["movement_id"] == "log:1"
        assert row["moved_from_key"] == f"BEP20|{h}|USDT|log:0"
        assert _bal(CLIA_ID, "USDT") == 100.0
        # B con el MISMO movimiento log:1 → 409 (A y B jamás juntos)
        dep_b = _mk_deposit(f"dep_{MARK}_r2", amount=100.0, tx_hash=h,
                            network="BEP20")
        r2 = _confirm(dep_b["id"], {"evidence_movement_id": "log:1"})
        assert r2.status_code == 409, r2.text
        det = r2.json()["detail"]
        assert isinstance(det, dict) and det["code"] == "EVIDENCE_ALREADY_USED"
        assert _bal(CLIA_ID, "USDT") == 100.0
        # una transferencia realmente distinta sigue acreditándose
        r3 = _confirm(dep_b["id"], {"evidence_movement_id": "log:2"})
        assert r3.status_code == 200, r3.text
        assert _bal(CLIA_ID, "USDT") == 200.0

    def test_resumption_same_identity_still_resumes(self):
        """Regresión: la reanudación con la MISMA identidad (reserva propia
        del intento interrumpido) sigue confirmando y acredita una vez."""
        h = f"{MARK}hash_same"
        dep = _mk_deposit(f"dep_{MARK}_r3", amount=100.0, tx_hash=h,
                          network="BEP20")
        _db().crypto_evidence_claims.insert_one({
            "claim_key": f"BEP20|{h}|USDT|", "deposit_id": dep["id"],
            "user_id": CLIA_ID, "network": "BEP20", "tx_hash": h,
            "currency": "USDT", "amount": 100.0, "movement_id": "",
            "at": _now()})
        _set_bal(CLIA_ID, "USDT", 0)
        r = _confirm(dep["id"])
        assert r.status_code == 200, r.text
        assert _bal(CLIA_ID, "USDT") == 100.0


# ---------------------------------------------------------------------------
# DE01 v2 — mínimo con aritmética decimal + protegido en la confirmación
# ---------------------------------------------------------------------------
class TestDE01MinDecimal:
    def _deposit(self, body, token=CLIA_TOKEN):
        return requests.post(f"{API}/deposits", headers=_h(token), json=body)

    def test_near_one_amounts_rejected_without_rounding(self):
        """Reproducción crypto_minimum (variante A): los importes bajo 1 muy
        próximos ya no se validan como 1 por el redondeo previo."""
        for i, amt in enumerate((0.99995, 0.99999, 0.99999999)):
            r = self._deposit({"currency": CRYPTO_ID, "amount": amt,
                               "method": "crypto",
                               "tx_hash": f"{MARK}hash_min_a{i}"})
            assert r.status_code == 422, f"{amt}: {r.text}"
            assert "mínimo" in r.json()["detail"]

    def test_exactly_one_and_above_accepted(self):
        for i, amt in enumerate((1, 1.00000001)):
            r = self._deposit({"currency": CRYPTO_ID, "amount": amt,
                               "method": "crypto",
                               "tx_hash": f"{MARK}hash_min_b{i}"})
            assert r.status_code == 200, f"{amt}: {r.text}"

    def test_confirm_blocked_without_rate_then_below_min(self):
        """Reproducción crypto_minimum (variante B): sin tasa la solicitud
        entra a revisión, pero la CONFIRMACIÓN queda bloqueada hasta resolver
        una equivalencia que cumpla el mínimo; con tasa que lo incumple sigue
        el 409 y jamás se acredita bajo el mínimo."""
        db = _db()
        db.rates.delete_many({"from_code": CRYPTO_NR})
        dep1 = _mk_deposit(f"dep_{MARK}_m1", amount=0.00000001,
                           currency=CRYPTO_NR, tx_hash=f"{MARK}hash_m1")
        _set_bal(CLIA_ID, CRYPTO_NR, 0)
        try:
            r = _confirm(dep1["id"])
            assert r.status_code == 409, r.text
            assert "tasa" in r.json()["detail"]
            # se configura la tasa: 0.00000001 × 100000 = 0.001 USDT < 1
            db.rates.update_one(
                {"from_code": CRYPTO_NR, "to_code": "USDT"},
                {"$set": {"from_code": CRYPTO_NR, "to_code": "USDT",
                          "rate_normal": 100000.0, "rate_vip": 100000.0,
                          "real_rate": 100000.0}}, upsert=True)
            r2 = _confirm(dep1["id"])
            assert r2.status_code == 409, r2.text
            assert "mínimo" in r2.json()["detail"]
            assert _bal(CLIA_ID, CRYPTO_NR) == 0.0, "jamás acredita bajo el mínimo"
            assert db.deposits.find_one({"id": dep1["id"]})["status"] == "pending"
            # un depósito que cumple (0.00001001 × 100000 = 1.001) confirma y
            # guarda la valoración que respalda la decisión
            dep2 = _mk_deposit(f"dep_{MARK}_m2", amount=0.00001001,
                               currency=CRYPTO_NR, tx_hash=f"{MARK}hash_m2")
            r3 = _confirm(dep2["id"])
            assert r3.status_code == 200, r3.text
            fresh = db.deposits.find_one({"id": dep2["id"]})
            val = fresh.get("min_crypto_valuation") or {}
            assert val.get("usdt_equivalent") == "1.00100000", val
            assert _bal(CLIA_ID, CRYPTO_NR) == 0.00001001
        finally:
            db.rates.delete_many({"from_code": CRYPTO_NR})

    def test_fiat_deposits_unaffected(self):
        r = self._deposit({"currency": FIAT_TR, "amount": 0.5,
                           "method": "cash"})
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# DR10 — el aviso «Nuevo retiro» se invoca en transferencia y cripto
# ---------------------------------------------------------------------------
class TestDR10AdminAlert:
    def test_transfer_and_crypto_invoke_admin_alert_once_each(self):
        """Reproducción withdrawal_admin_alert: ambos métodos invocan el aviso
        exactamente una vez, con el débito correcto (sin UnboundLocalError)."""
        _set_bal(CLIA_ID, FIAT_TR, 500.0)
        _set_bal(CLIA_ID, CRYPTO_ID, 500.0)
        calls = []

        async def flow():
            import routes.orders as ro
            import admin_alerts
            orig_notify = admin_alerts.notify_all_admins
            orig_require = ro.require_user
            orig_verified = ro.assert_user_fully_verified
            orig_totp = ro._enforce_totp_step_up

            async def spy(db_, *, title, body, url_path="/admin"):
                calls.append(title)
                return {"admins": 0, "pushes": 0, "emails": 0}

            async def fake_user(request):
                from db_client import db as adb
                return await adb.users.find_one({"user_id": CLIA_ID},
                                                {"_id": 0})

            async def noop(*a, **k):
                return None

            admin_alerts.notify_all_admins = spy
            ro.require_user = fake_user
            ro.assert_user_fully_verified = noop
            ro._enforce_totp_step_up = noop
            try:
                req = types.SimpleNamespace(client=None, headers={})
                w1 = await ro.create_withdrawal(ro.WithdrawalCreate(
                    amount_usd=10, currency=FIAT_TR, method="transfer",
                    details="9584 7203 1146 8892",
                    beneficiary_name="Titular Prueba"), req)
                w2 = await ro.create_withdrawal(ro.WithdrawalCreate(
                    amount_usd=10, currency=CRYPTO_ID, method="crypto",
                    details=TRC20_ADDR, crypto_network="TRC20"), req)
            finally:
                admin_alerts.notify_all_admins = orig_notify
                ro.require_user = orig_require
                ro.assert_user_fully_verified = orig_verified
                ro._enforce_totp_step_up = orig_totp
            return w1, w2

        w1, w2 = _run(flow)
        assert calls.count("Nuevo retiro") == 2, \
            f"cada retiro invoca el aviso una vez: {calls}"
        assert w1["status"] == "pending" and w2["status"] == "pending"
        assert _bal(CLIA_ID, FIAT_TR) == 490.0
        assert _bal(CLIA_ID, CRYPTO_ID) == 490.0


# ---------------------------------------------------------------------------
# CI — la suite queda en el conjunto crítico
# ---------------------------------------------------------------------------
class TestCICoverage:
    def test_makefile_critical_includes_iter303(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter303_verificacion_dr2.py" in target
