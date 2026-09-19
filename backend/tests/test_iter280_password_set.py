"""iter280 — Establecer contraseña para cuentas creadas con Google.

Bug reportado (19 sep 2026): un usuario registrado con Google no puede crear
una contraseña porque «Cambiar contraseña» exige la actual, que nunca existió.

Nuevo endpoint: `POST /api/profile/password/set` con `{new_password,
totp_code?}`. Reglas:
  - Solo cuentas SIN `password_hash` (si ya existe → 400, usar el cambio).
  - 2FA step-up si el usuario lo tiene activado.
  - Tras establecerla: login por correo+contraseña funciona, las demás
    sesiones se revocan y `/profile/me` expone `has_password`.
"""
import os
import secrets
from datetime import datetime, timezone

import bcrypt
import pyotp
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL as API_ROOT, TEST_TOTP_SECRET

API = f"{API_ROOT}/api"

TEST_EMAIL = "pwd.set.test@resilience.com"
TEST_UID = "user_test_pwdset01"
TEST_SESSION = f"test_session_pwdset_{secrets.token_hex(8)}"
EXTRA_SESSION = f"test_session_pwdset_other_{secrets.token_hex(4)}"
NEW_PW = "MiPrimeraClave123!"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {TEST_SESSION}",
            "Content-Type": "application/json"}


def _fresh_totp() -> str:
    return pyotp.TOTP(TEST_TOTP_SECRET).now()


def _setup_google_user(twofa_enabled: bool = False, with_password: bool = False):
    db_ = _db()
    doc = {
        "user_id": TEST_UID,
        "email": TEST_EMAIL,
        "name": "PwdSet Test",
        "role": "normal",
        "auth_provider": "google",
        "email_verified": True,
        "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "totp_enabled": False,
    }
    if twofa_enabled:
        import totp_service as _ts
        doc["totp_enabled"] = True
        doc["totp_secret_encrypted"] = _ts.encrypt_secret(TEST_TOTP_SECRET)
        doc["totp_recovery_codes"] = []
    if with_password:
        doc["password_hash"] = bcrypt.hashpw(
            b"YaTengoClave123!", bcrypt.gensalt()).decode()
    db_.users.delete_many({"user_id": TEST_UID})
    db_.users.insert_one(doc)
    now = datetime.now(timezone.utc)
    db_.user_sessions.update_one(
        {"session_token": TEST_SESSION},
        {"$set": {"session_token": TEST_SESSION, "user_id": TEST_UID,
                  "expires_at": now.replace(year=now.year + 1),
                  "created_at": now}},
        upsert=True,
    )


def _cleanup():
    db_ = _db()
    db_.users.delete_many({"user_id": TEST_UID})
    db_.user_sessions.delete_many({"user_id": TEST_UID})
    db_.audit_log.delete_many({"actor_id": TEST_UID})
    db_.login_attempts.delete_many({"identifier": {"$regex": TEST_EMAIL}})


def test_profile_me_exposes_has_password():
    _setup_google_user()
    try:
        r = requests.get(f"{API}/profile/me", headers=_hdr())
        assert r.status_code == 200, r.text
        assert r.json()["has_password"] is False
    finally:
        _cleanup()


def test_set_password_then_email_login_works():
    """Aceptación del reporte: la cuenta Google crea su primera contraseña y
    con ella puede entrar por correo+contraseña."""
    _setup_google_user()
    try:
        r = requests.post(f"{API}/profile/password/set", headers=_hdr(),
                          json={"new_password": NEW_PW})
        assert r.status_code == 200, r.text
        u = _db().users.find_one({"user_id": TEST_UID}, {"_id": 0})
        assert u["password_hash"].startswith("$2b$")
        assert bcrypt.checkpw(NEW_PW.encode(), u["password_hash"].encode())
        assert u.get("password_changed_at")

        me = requests.get(f"{API}/profile/me", headers=_hdr()).json()
        assert me["has_password"] is True

        login = requests.post(f"{API}/auth/login",
                              json={"email": TEST_EMAIL, "password": NEW_PW})
        assert login.status_code == 200, login.text
        assert login.json()["user_id"] == TEST_UID
        assert "password_hash" not in login.json()
    finally:
        _cleanup()


def test_set_password_rejected_if_already_exists():
    """Con contraseña existente → 400: ahí aplica el flujo de CAMBIO (que
    verifica la actual). Nunca se sobreescribe sin verificación."""
    _setup_google_user(with_password=True)
    try:
        r = requests.post(f"{API}/profile/password/set", headers=_hdr(),
                          json={"new_password": NEW_PW})
        assert r.status_code == 400, r.text
        u = _db().users.find_one({"user_id": TEST_UID}, {"_id": 0})
        assert bcrypt.checkpw(b"YaTengoClave123!", u["password_hash"].encode())
    finally:
        _cleanup()


def test_set_password_requires_totp_when_enabled():
    _setup_google_user(twofa_enabled=True)
    try:
        r = requests.post(f"{API}/profile/password/set", headers=_hdr(),
                          json={"new_password": NEW_PW})
        assert r.status_code in (400, 401, 403), r.text
        assert not _db().users.find_one(
            {"user_id": TEST_UID}, {"_id": 0}).get("password_hash")

        ok = requests.post(f"{API}/profile/password/set", headers=_hdr(),
                           json={"new_password": NEW_PW,
                                 "totp_code": _fresh_totp()})
        assert ok.status_code == 200, ok.text
    finally:
        _cleanup()


def test_set_password_revokes_other_sessions():
    _setup_google_user()
    db_ = _db()
    now = datetime.now(timezone.utc)
    db_.user_sessions.update_one(
        {"session_token": EXTRA_SESSION},
        {"$set": {"session_token": EXTRA_SESSION, "user_id": TEST_UID,
                  "expires_at": now.replace(year=now.year + 1),
                  "created_at": now}},
        upsert=True,
    )
    try:
        r = requests.post(f"{API}/profile/password/set", headers=_hdr(),
                          json={"new_password": NEW_PW})
        assert r.status_code == 200, r.text
        assert r.json()["other_sessions_revoked"] == 1
        remaining = list(db_.user_sessions.find({"user_id": TEST_UID}))
        assert len(remaining) == 1
        assert remaining[0]["session_token"] == TEST_SESSION
    finally:
        _cleanup()
        db_.user_sessions.delete_many({"session_token": EXTRA_SESSION})


def test_set_password_min_length_enforced():
    _setup_google_user()
    try:
        r = requests.post(f"{API}/profile/password/set", headers=_hdr(),
                          json={"new_password": "corta"})
        assert r.status_code == 422, r.text
    finally:
        _cleanup()


def test_change_password_works_after_set():
    """Ciclo completo: establecer → cambiar con la actual → login con la nueva."""
    _setup_google_user()
    try:
        assert requests.post(f"{API}/profile/password/set", headers=_hdr(),
                             json={"new_password": NEW_PW}).status_code == 200
        chg = requests.post(f"{API}/profile/password/change", headers=_hdr(),
                            json={"current_password": NEW_PW,
                                  "new_password": "OtraClaveNueva456!"})
        assert chg.status_code == 200, chg.text
        login = requests.post(
            f"{API}/auth/login",
            json={"email": TEST_EMAIL, "password": "OtraClaveNueva456!"})
        assert login.status_code == 200, login.text
    finally:
        _cleanup()
