"""F2-04 / EMP03 — El catálogo ya NO sobrescribe stock.

- Editar metadatos (nombre/precio/descripción) NUNCA cambia el stock vigente
  (el stock se gestiona solo con movimientos auditados de inventario).
- Decimales de extremo a extremo: un producto 'libra'/'kg' conserva 2,5.
- Coherencia de unidades: 'unidad' rechaza fracciones; 'libra'/'kg' las admite.
- Stock inicial = movimiento auditado 'receive' (no un $set silencioso).
- Ajuste ABSOLUTO del total con control de versión (CAS) y traza, idempotente.
"""
import os
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa_f204"
EMP_TOKEN = "test_session_empresa_f204_X"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr():
    return {"Authorization": f"Bearer {EMP_TOKEN}", "Content-Type": "application/json"}


def _seed():
    d = _db()
    d.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa.f204@example.com",
        "name": "Empresa F204", "role": "empresa", "account_status": "active",
        "email_verified": True, "phone_verified": True, "phone": "+5350000244"}},
        upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    d.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)


def _cleanup():
    d = _db()
    d.products.delete_many({"company_id": EMP_ID})
    d.stores.delete_many({"company_id": EMP_ID})
    d.company_inventory_moves.delete_many({"company_id": EMP_ID})
    d.company_inventory_ops.delete_many({"company_id": EMP_ID})


def _mk_product(unit="unidad", stock=0):
    r = requests.post(f"{API}/company/products", headers=_hdr(), json={
        "name": f"Prod {unit}", "price_usd": 2.0, "stock": stock, "unit": unit}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _receive(pid, qty):
    return requests.post(f"{API}/company/inventory/receive", headers=_hdr(),
                         json={"product_id": pid, "qty": qty}, timeout=15)


def _row(pid):
    r = requests.get(f"{API}/company/inventory", headers=_hdr(), timeout=15)
    assert r.status_code == 200, r.text
    for row in r.json():
        if row["product_id"] == pid:
            return row
    return None


def _moves(pid, mtype):
    moves = requests.get(f"{API}/company/inventory/moves", headers=_hdr(), timeout=15).json()
    return [m for m in moves if m.get("type") == mtype]


# ------------------------- edición de metadatos -------------------------

def test_edit_metadata_does_not_touch_stock():
    """Tras recibir 10, editar el nombre (incluso enviando stock antiguo) NO
    revierte el stock vigente."""
    _seed(); _cleanup()
    pid = _mk_product("unidad", 0)
    assert _receive(pid, 10).status_code == 200
    assert _row(pid)["total"] == 10
    # intenta colar stock=999 en la edición de metadatos → debe ignorarse
    r = requests.put(f"{API}/company/products/{pid}", headers=_hdr(),
                     json={"name": "Nuevo nombre", "stock": 999}, timeout=15)
    assert r.status_code == 200, r.text
    assert _row(pid)["total"] == 10                  # stock intacto
    assert _db().products.find_one({"id": pid})["stock"] == 10
    assert _db().products.find_one({"id": pid})["name"] == "Nuevo nombre"
    _cleanup()


def test_edit_preserves_decimal_stock():
    """Un producto 'libra' con 2,5: cambiar la descripción mantiene exactamente 2,5."""
    _seed(); _cleanup()
    pid = _mk_product("libra", 0)
    assert _receive(pid, 2.5).status_code == 200
    assert _row(pid)["total"] == 2.5
    r = requests.put(f"{API}/company/products/{pid}", headers=_hdr(),
                     json={"description": "Arroz a granel"}, timeout=15)
    assert r.status_code == 200, r.text
    assert _row(pid)["total"] == 2.5                 # decimal preservado
    _cleanup()


# ------------------------- stock inicial auditado -------------------------

def test_initial_stock_is_audited_receive():
    """El stock inicial del alta entra como un movimiento 'receive' auditado."""
    _seed(); _cleanup()
    pid = _mk_product("unidad", 5)
    assert _row(pid)["total"] == 5
    assert len(_moves(pid, "receive")) == 1          # traza del alta
    _cleanup()


# ------------------------- coherencia de unidades -------------------------

def test_unit_integer_rejects_fraction():
    """Un producto 'unidad' no admite recibir fracciones → 400."""
    _seed(); _cleanup()
    pid = _mk_product("unidad", 0)
    r = _receive(pid, 2.5)
    assert r.status_code == 400, r.text
    assert _row(pid)["total"] == 0                   # sin efecto
    # y tampoco se puede crear 'unidad' con fracción inicial
    r = requests.post(f"{API}/company/products", headers=_hdr(), json={
        "name": "Entero frac", "price_usd": 1.0, "stock": 1.5, "unit": "unidad"}, timeout=15)
    assert r.status_code == 400, r.text
    _cleanup()


def test_unit_decimal_allows_fraction():
    """Un producto 'kg' admite fracciones de extremo a extremo."""
    _seed(); _cleanup()
    pid = _mk_product("kg", 0)
    assert _receive(pid, 2.5).status_code == 200
    assert _row(pid)["total"] == 2.5
    _cleanup()


# ------------------------- ajuste absoluto (versión + traza) -------------------------

def test_adjust_absolute_with_version_and_trace():
    """Ajuste absoluto con el total esperado correcto aplica y deja traza."""
    _seed(); _cleanup()
    pid = _mk_product("unidad", 0)
    _receive(pid, 10)
    r = requests.post(f"{API}/company/inventory/adjust", headers=_hdr(),
                      json={"product_id": pid, "new_total": 7, "expected_total": 10}, timeout=15)
    assert r.status_code == 200, r.text
    assert _row(pid)["total"] == 7
    assert len(_moves(pid, "adjust")) == 1
    _cleanup()


def test_adjust_stale_expected_total_conflicts():
    """Si el total esperado no coincide con el vigente → 409 (recargar)."""
    _seed(); _cleanup()
    pid = _mk_product("unidad", 0)
    _receive(pid, 10)
    r = requests.post(f"{API}/company/inventory/adjust", headers=_hdr(),
                      json={"product_id": pid, "new_total": 7, "expected_total": 4}, timeout=15)
    assert r.status_code == 409, r.text
    assert _row(pid)["total"] == 10                  # sin efecto
    _cleanup()


def test_adjust_below_distributed_rejected():
    """El total no puede quedar por debajo de lo ya distribuido a tiendas → 409."""
    _seed(); _cleanup()
    pid = _mk_product("unidad", 0)
    _receive(pid, 10)
    sa = requests.post(f"{API}/company/stores", headers=_hdr(), json={
        "name": "Tienda F204", "address": "Dir F204 larga"}, timeout=15).json()["id"]
    assert requests.post(f"{API}/company/inventory/distribute", headers=_hdr(),
                         json={"product_id": pid, "store_id": sa, "qty": 6}, timeout=15).status_code == 200
    r = requests.post(f"{API}/company/inventory/adjust", headers=_hdr(),
                      json={"product_id": pid, "new_total": 4, "expected_total": 10}, timeout=15)
    assert r.status_code == 409, r.text
    assert _row(pid)["total"] == 10                  # sin efecto
    _cleanup()


def test_adjust_is_idempotent_by_op_id():
    """Reintentar el ajuste con la MISMA clave no lo aplica dos veces."""
    _seed(); _cleanup()
    pid = _mk_product("unidad", 0)
    _receive(pid, 10)
    body = {"product_id": pid, "new_total": 7, "expected_total": 10, "op_id": "adj-fixed-1"}
    r1 = requests.post(f"{API}/company/inventory/adjust", headers=_hdr(), json=body, timeout=15)
    r2 = requests.post(f"{API}/company/inventory/adjust", headers=_hdr(), json=body, timeout=15)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert _row(pid)["total"] == 7                   # un solo ajuste
    assert len(_moves(pid, "adjust")) == 1
    _cleanup()
