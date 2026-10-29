"""Regresión de la auditoría de Empresas de Servicios (Resilience_Revision_Servicios).

Cubre los hallazgos corregidos:
  SV-01  La oferta solo es visible si el propietario sigue HABILITADO
         (rol empresa + cuenta activa). Suspensión / rol cambiado / cuenta
         eliminada ocultan catálogo y ficha, sin borrar el servicio.
  SV-02  Un precio sub-céntimo (0.001) que se guardaría como 0.00 se rechaza;
         «A presupuestar» sigue admitiendo 0.
  SV-03  Anticipo %>100, zona horaria no IANA, fecha bloqueada no ISO,
         categoría inexistente/inactiva y anticipo fijo > precio total se
         rechazan; una configuración válida pasa.

Suite AUTOCONTENIDA y repetible: siembra su propio usuario/sesión Empresa con
pymongo y limpia todo al final (no depende de sesiones smoke externas).
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MARK = f"SVAUDIT_{uuid.uuid4().hex[:8]}"
EMP_TOKEN = f"svaudit_empresa_{uuid.uuid4().hex[:6]}"
EMP_UID = f"user_svaudit_empresa_{uuid.uuid4().hex[:6]}"
EMP = {"session_token": EMP_TOKEN}

_service_ids: list[str] = []
_user_ids: list[str] = []


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_user(uid: str, role: str = "empresa", status: str = "active") -> str:
    _db().users.update_one({"user_id": uid}, {"$set": {
        "user_id": uid, "role": role, "account_status": status,
        "name": f"{MARK} owner", "email": f"{uid}@test.local",
        "email_verified": True, "phone_verified": True, "company_id": uid,
    }}, upsert=True)
    _user_ids.append(uid)
    return uid


def _seed_published_service(owner_id: str, suffix: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    sid = str(uuid.uuid4())
    _db().services.insert_one({
        "id": sid, "company_id": owner_id, "owner_name": f"{MARK}",
        "title": f"{MARK} {suffix}", "category": "limpieza", "description": "",
        "images": [], "modality": "domicilio", "pricing_type": "fixed",
        "price_usdt": 25.0, "deposit_type": "none", "deposit_value": 0.0,
        "duration_minutes": 60, "min_notice_hours": 0, "capacity": 1,
        "buffer_minutes": 0, "coverage_zone": "Vedado", "requirements": "",
        "inclusions": "", "exclusions": "", "cancellation_policy": "",
        "payment_methods": ["balance"],
        "availability": [{"day": 0, "start": "09:00", "end": "12:00"}],
        "blocked_dates": [], "timezone": "America/Havana", "status": "published",
        "rejection_reason": "", "is_active": True, "created_at": now,
        "updated_at": now, "approved_at": now,
    })
    _service_ids.append(sid)
    return sid


@pytest.fixture(scope="module", autouse=True)
def seed():
    db = _db()
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    _seed_user(EMP_UID, "empresa", "active")
    db.user_sessions.update_one(
        {"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_UID, "expires_at": exp}},
        upsert=True)
    yield
    db.services.delete_many({"title": {"$regex": f"^{MARK}"}})
    for sid in _service_ids:
        db.services.delete_one({"id": sid})
    for uid in _user_ids:
        db.users.delete_one({"user_id": uid})
    db.user_sessions.delete_one({"session_token": EMP_TOKEN})


def _catalog_ids():
    r = requests.get(f"{API}/services")
    assert r.status_code == 200
    return [s["id"] for s in r.json()]


def _create(**kw):
    p = {"title": f"{MARK} svc {uuid.uuid4().hex[:5]}", "category": "limpieza",
         "modality": "domicilio", "pricing_type": "fixed", "price_usdt": 25,
         "availability": [{"day": 0, "start": "09:00", "end": "12:00"}],
         "payment_methods": ["balance"], "coverage_zone": "Vedado", "submit": False}
    p.update(kw)
    r = requests.post(f"{API}/company/services", json=p, cookies=EMP)
    if r.status_code == 200:
        _service_ids.append(r.json()["id"])
    return r


# --------------------------------------------------------------------------
# SV-01 — elegibilidad operativa del propietario
# --------------------------------------------------------------------------

def test_sv01_active_owner_visible():
    sid = _seed_published_service(EMP_UID, "active-offer")
    assert sid in _catalog_ids()
    assert requests.get(f"{API}/services/{sid}").status_code == 200


def test_sv01_suspended_owner_hidden():
    uid = _seed_user(f"user_svaudit_susp_{uuid.uuid4().hex[:6]}", "empresa", "under_review")
    sid = _seed_published_service(uid, "suspended-offer")
    assert sid not in _catalog_ids()
    assert requests.get(f"{API}/services/{sid}").status_code == 404


def test_sv01_role_changed_owner_hidden():
    uid = _seed_user(f"user_svaudit_role_{uuid.uuid4().hex[:6]}", "normal", "active")
    sid = _seed_published_service(uid, "rolechg-offer")
    assert sid not in _catalog_ids()
    assert requests.get(f"{API}/services/{sid}").status_code == 404


def test_sv01_deleted_owner_hidden():
    # Propietario inexistente (cuenta eliminada): no se siembra el usuario.
    orphan = f"user_svaudit_deleted_{uuid.uuid4().hex[:6]}"
    sid = _seed_published_service(orphan, "orphan-offer")
    assert sid not in _catalog_ids()
    assert requests.get(f"{API}/services/{sid}").status_code == 404


def test_sv01_reactivation_restores_visibility():
    uid = _seed_user(f"user_svaudit_react_{uuid.uuid4().hex[:6]}", "empresa", "under_review")
    sid = _seed_published_service(uid, "react-offer")
    assert sid not in _catalog_ids()
    _db().users.update_one({"user_id": uid}, {"$set": {"account_status": "active"}})
    assert sid in _catalog_ids()


# --------------------------------------------------------------------------
# SV-02 — precisión monetaria
# --------------------------------------------------------------------------

def test_sv02_subcent_price_rejected():
    r = _create(price_usdt=0.001)
    assert r.status_code == 400, r.text


def test_sv02_zero_price_rejected():
    assert _create(price_usdt=0).status_code == 400


def test_sv02_quote_allows_zero():
    r = _create(pricing_type="quote", price_usdt=0)
    assert r.status_code == 200 and r.json()["pricing_type"] == "quote"


def test_sv02_normal_price_ok():
    r = _create(price_usdt=25)
    assert r.status_code == 200 and r.json()["price_usdt"] == 25


# --------------------------------------------------------------------------
# SV-03 — validación de anticipo y configuración
# --------------------------------------------------------------------------

def test_sv03_deposit_percent_over_100_rejected():
    assert _create(deposit_type="percent", deposit_value=250).status_code == 400


def test_sv03_invalid_timezone_rejected():
    assert _create(timezone="Invalid/Zone").status_code == 400


def test_sv03_invalid_blocked_date_rejected():
    assert _create(blocked_dates=["2026-99-99"]).status_code == 400


def test_sv03_nonexistent_category_rejected():
    assert _create(category=f"nope_{uuid.uuid4().hex[:6]}").status_code == 400


def test_sv03_fixed_deposit_over_total_rejected():
    assert _create(pricing_type="fixed", price_usdt=20,
                   deposit_type="fixed", deposit_value=50).status_code == 400


def test_sv03_hourly_fixed_deposit_not_compared_to_unit():
    # Para precios por hora el anticipo NO se compara contra una sola unidad.
    r = _create(pricing_type="hourly", price_usdt=10,
                deposit_type="fixed", deposit_value=40)
    assert r.status_code == 200, r.text


def test_sv03_valid_config_ok():
    r = _create(deposit_type="percent", deposit_value=30, timezone="America/Havana",
                blocked_dates=["2026-07-04"], category="limpieza")
    assert r.status_code == 200, r.text
