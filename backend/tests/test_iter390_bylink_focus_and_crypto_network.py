"""iter390 — Regresiones para los últimos cambios:

A) Endpoints "buscar por ID" que alimentan el resaltado exacto (focus) desde
   Transacciones hacia el registro de origen, aunque esté fuera de la lista
   cargada / en otra página / otro estado:
     - GET /api/admin/withdrawals/{wid}
     - GET /api/admin/company-funds/movements/{mid}   (retiro o ajuste)
     - GET /api/admin/vip-batches/items/{item_id}
   Cada uno: 200 con el registro correcto, 404 para id inexistente, y gating de
   permiso (un cliente normal no puede).

B) Red obligatoria en cuentas de cobro CRIPTO:
     - crear cuenta cripto SIN red → 400 (antes de pedir TOTP).
     - crear cuenta cripto CON red → 200.
     - crear cuenta FIAT sin red → 200 (la red es opcional para fiat).
     - editar (PUT) quitando la red de una cuenta cripto → 400.

C) Cuentas creadas con Google ahora pueden ESTABLECER contraseña vía el flujo
   "olvidé mi contraseña" (bug reportado 2 nov 2026). Antes forgot-password NO
   emitía token para cuentas sin password_hash; ahora sí. Tras establecerla:
     - login con la nueva contraseña funciona.
     - login con contraseña errónea → 401 INVALID_CREDENTIALS (ya NO
       USE_GOOGLE_LOGIN, porque ya existe password_hash).

Los tests se ejecutan contra REACT_APP_BACKEND_URL; conftest inyecta el bypass
de captcha y siembra las sesiones de prueba.
"""
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import requests
from pymongo import MongoClient

from tests.conftest import ADMIN_TOKEN, BASE_URL, NORMAL_TOKEN, make_admin_totp

API = f"{BASE_URL}/api"

# ---- deterministic test ids ----
WD_ID = "wd_iter390_byid01"
CWD_ID = "cwd_iter390_byid01"
CADJ_ID = "cadj_iter390_byid01"
VBI_ID = "vbi_iter390_byid01"
CRYPTO_CODE = "Z390C"   # moneda cripto sintética sólo para esta suite
FIAT_CODE = "Z390F"     # moneda fiat sintética sólo para esta suite
GOOGLE_EMAIL = "glink.forgot390@resilience.com"
GOOGLE_UID = "user_iter390_google01"
NEW_PW = "ClaveNuevaGoogle390!"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(dt):
    return dt.isoformat()


def setup_module(_module):
    db = _db()
    now = _iso(datetime.now(timezone.utc))

    # A1 — retiro (transfer → _attach_courier_status es no-op)
    db.withdrawals.delete_many({"id": WD_ID})
    db.withdrawals.insert_one({
        "id": WD_ID, "user_id": "user_test_normal01",
        "user_email": "normal.test@resilience.com", "user_name": "QA Normal",
        "currency": "EUR", "amount": 123.45, "method": "transfer",
        "status": "pending", "created_at": now, "updated_at": now,
    })

    # A2 — movimiento del fondo: un retiro de empresa y un ajuste (entrada)
    db.company_withdrawals.delete_many({"id": CWD_ID})
    db.company_withdrawals.insert_one({
        "id": CWD_ID, "currency": "USD", "amount": 500.0,
        "beneficiary": "QA Beneficiary", "status": "pending",
        "created_at": now, "updated_at": now,
    })
    db.company_fund_adjustments.delete_many({"id": CADJ_ID})
    db.company_fund_adjustments.insert_one({
        "id": CADJ_ID, "currency": "USD", "amount": 80.0,
        "adjustment_type": "inflow", "reason": "QA test adjust",
        "created_at": now,
    })

    # A3 — ítem de lote VIP (vip_user_id = usuario VIP de prueba existente)
    db.vip_batch_items.delete_many({"id": VBI_ID})
    db.vip_batch_items.insert_one({
        "id": VBI_ID, "batch_id": "batch_iter390", "vip_user_id": "user_test_vip01",
        "from_code": "USDT", "to_code": "EUR", "amount": 100.0,
        "status": "pending", "created_at": now,
    })

    # B — monedas sintéticas (cripto + fiat)
    db.currencies.update_one({"code": CRYPTO_CODE}, {"$set": {
        "id": "cur_iter390_crypto", "code": CRYPTO_CODE, "name": "iter390 Crypto",
        "type": "crypto", "symbol": "₮", "is_active": True, "payment_account": "",
    }}, upsert=True)
    db.currencies.update_one({"code": FIAT_CODE}, {"$set": {
        "id": "cur_iter390_fiat", "code": FIAT_CODE, "name": "iter390 Fiat",
        "type": "fiat", "symbol": "$", "is_active": True, "payment_account": "",
    }}, upsert=True)
    db.payment_accounts.delete_many({"currency_code": {"$in": [CRYPTO_CODE, FIAT_CODE]}})

    # C — usuario creado con Google (sin password_hash)
    db.users.delete_many({"user_id": GOOGLE_UID})
    db.users.insert_one({
        "user_id": GOOGLE_UID, "email": GOOGLE_EMAIL, "name": "G Link",
        "role": "normal", "auth_provider": "google", "email_verified": True,
        "account_status": "active", "created_at": now, "session_version": 0,
    })
    db.login_attempts.delete_many({"identifier": {"$regex": GOOGLE_EMAIL}})


def teardown_module(_module):
    db = _db()
    db.withdrawals.delete_many({"id": WD_ID})
    db.company_withdrawals.delete_many({"id": CWD_ID})
    db.company_fund_adjustments.delete_many({"id": CADJ_ID})
    db.vip_batch_items.delete_many({"id": VBI_ID})
    db.payment_accounts.delete_many({"currency_code": {"$in": [CRYPTO_CODE, FIAT_CODE]}})
    db.currencies.delete_many({"code": {"$in": [CRYPTO_CODE, FIAT_CODE]}})
    db.users.delete_many({"user_id": GOOGLE_UID})
    db.user_sessions.delete_many({"user_id": GOOGLE_UID})
    db.login_attempts.delete_many({"identifier": {"$regex": GOOGLE_EMAIL}})


# ---------------------------------------------------------------------------
# A) Endpoints "buscar por ID"
# ---------------------------------------------------------------------------
def test_withdrawal_by_id_ok():
    r = requests.get(f"{API}/admin/withdrawals/{WD_ID}", headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == WD_ID
    assert r.json()["currency"] == "EUR"


def test_withdrawal_by_id_404():
    r = requests.get(f"{API}/admin/withdrawals/nope_{uuid.uuid4().hex}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 404, r.text


def test_withdrawal_by_id_requires_permission():
    r = requests.get(f"{API}/admin/withdrawals/{WD_ID}", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code in (401, 403), r.text


def test_company_movement_by_id_withdrawal():
    r = requests.get(f"{API}/admin/company-funds/movements/{CWD_ID}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == CWD_ID
    assert body["kind"] == "withdrawal"


def test_company_movement_by_id_adjustment():
    r = requests.get(f"{API}/admin/company-funds/movements/{CADJ_ID}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == CADJ_ID
    # inflow → kind "deposit"
    assert body["kind"] in ("deposit", "adjust_out")


def test_company_movement_by_id_404():
    r = requests.get(f"{API}/admin/company-funds/movements/nope_{uuid.uuid4().hex}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 404, r.text


def test_company_movement_by_id_requires_permission():
    r = requests.get(f"{API}/admin/company-funds/movements/{CWD_ID}",
                     headers=_hdr(NORMAL_TOKEN))
    assert r.status_code in (401, 403), r.text


def test_vip_batch_item_by_id_ok():
    r = requests.get(f"{API}/admin/vip-batches/items/{VBI_ID}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == VBI_ID
    assert body["pair"] == "USDT→EUR"


def test_vip_batch_item_by_id_404():
    r = requests.get(f"{API}/admin/vip-batches/items/nope_{uuid.uuid4().hex}",
                     headers=_hdr(ADMIN_TOKEN))
    assert r.status_code == 404, r.text


def test_vip_batch_item_by_id_requires_permission():
    r = requests.get(f"{API}/admin/vip-batches/items/{VBI_ID}",
                     headers=_hdr(NORMAL_TOKEN))
    assert r.status_code in (401, 403), r.text


# ---------------------------------------------------------------------------
# B) Red obligatoria en cuentas de cobro cripto
# ---------------------------------------------------------------------------
def _create_account(**overrides):
    base = {
        "currency_code": CRYPTO_CODE,
        "label": f"Wallet {uuid.uuid4().hex[:6]}",
        "account_details": "0xabc... (iter390 test)",
        "network": "TRC20",
        "min_amount": 1,
        "is_active": True,
        "totp_code": make_admin_totp(),
    }
    base.update(overrides)
    return requests.post(f"{API}/admin/payment-accounts",
                         headers=_hdr(ADMIN_TOKEN), json=base)


def test_crypto_account_without_network_rejected():
    r = _create_account(network="")
    assert r.status_code == 400, r.text
    # el mensaje menciona la red (no es el error genérico de TOTP)
    assert "red" in r.text.lower()


def test_crypto_account_with_network_ok():
    r = _create_account(network="TRC20")
    assert r.status_code == 200, r.text
    assert r.json()["network"] == "TRC20"


def test_fiat_account_without_network_ok():
    r = _create_account(currency_code=FIAT_CODE, network="")
    assert r.status_code == 200, r.text
    assert r.json().get("network") in (None, "")


def test_crypto_account_update_removing_network_rejected():
    created = _create_account(network="BEP20")
    assert created.status_code == 200, created.text
    doc = created.json()
    put_body = {
        "currency_code": CRYPTO_CODE,
        "label": doc["label"],
        "account_details": doc["account_details"],
        "network": "",
        "min_amount": doc["min_amount"],
        "max_amount": doc.get("max_amount"),
        "is_active": True,
        "totp_code": make_admin_totp(),
    }
    r = requests.put(f"{API}/admin/payment-accounts/{doc['id']}",
                     headers=_hdr(ADMIN_TOKEN), json=put_body)
    assert r.status_code == 400, r.text
    assert "red" in r.text.lower()


# ---------------------------------------------------------------------------
# C) Google → establecer contraseña vía "olvidé mi contraseña"
# ---------------------------------------------------------------------------
def test_forgot_password_issues_token_for_google_account():
    """EL FIX: una cuenta creada con Google (sin password_hash) ahora recibe un
    token de recuperación. Antes forgot-password no hacía nada para estas
    cuentas."""
    db = _db()
    db.users.update_one({"user_id": GOOGLE_UID},
                        {"$unset": {"password_reset_token_hash": "",
                                    "password_reset_expires_at": ""}})
    r = requests.post(f"{API}/auth/forgot-password", json={"email": GOOGLE_EMAIL})
    assert r.status_code == 200, r.text
    u = db.users.find_one({"user_id": GOOGLE_UID}, {"_id": 0})
    assert u.get("password_reset_token_hash"), "no se emitió token para cuenta Google"


def test_google_set_password_then_login_and_wrong_password():
    db = _db()
    # emite + inyecta un token conocido (el enlace del correo no es accesible)
    requests.post(f"{API}/auth/forgot-password", json={"email": GOOGLE_EMAIL})
    token = "ITER390-KNOWN-TOKEN"
    db.users.update_one({"user_id": GOOGLE_UID}, {"$set": {
        "password_reset_token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "password_reset_expires_at": _iso(datetime.now(timezone.utc) + timedelta(hours=1)),
    }})

    rst = requests.post(f"{API}/auth/reset-password",
                        json={"token": token, "password": NEW_PW})
    assert rst.status_code == 200, rst.text
    u = db.users.find_one({"user_id": GOOGLE_UID}, {"_id": 0})
    assert u["password_hash"].startswith("$2b$")
    assert bcrypt.checkpw(NEW_PW.encode(), u["password_hash"].encode())

    ok = requests.post(f"{API}/auth/login",
                       json={"email": GOOGLE_EMAIL, "password": NEW_PW})
    assert ok.status_code == 200, ok.text
    assert ok.json()["user_id"] == GOOGLE_UID

    bad = requests.post(f"{API}/auth/login",
                        json={"email": GOOGLE_EMAIL, "password": "claveMala"})
    assert bad.status_code == 401, bad.text
    detail = bad.json()["detail"]
    code = detail.get("code") if isinstance(detail, dict) else detail
    assert code == "INVALID_CREDENTIALS", bad.text


def test_forgot_password_unknown_email_still_200():
    """Anti-enumeración: un correo inexistente responde 200 igualmente."""
    r = requests.post(f"{API}/auth/forgot-password",
                      json={"email": f"nobody_{uuid.uuid4().hex}@resilience.com"})
    assert r.status_code == 200, r.text
