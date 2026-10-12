"""MEN-04 — separación Activas / Pendientes de confirmación / Historial +
paginación de servidor + historial completo del mensajero.

- `?status=active` = EN CURSO (excluye delivered, confirmed, cancelled).
- `?status=pending_confirmation` = SOLO delivered (pendientes de pago/confirmación).
- `?status=history` = confirmed + cancelled.
- Paginación servidor: `skip`/`limit` + cabecera `X-Total-Count`.
- `GET /courier/deliveries/history` devuelve el historial COMPLETO paginado
  (no el tope fijo de 50 del panel).
"""
import os
import uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk(status="available", **extra):
    did = f"men04_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": did, "status": status, "kind": "withdrawal",
        "ref_id": uuid.uuid4().hex, "client_name": "MEN04",
        "amount_label": "100 USDT", "address": "Calle 1",
        "km": 2, "fee_usdt": 5, "courier_share_usdt": 4,
        "platform_share_usdt": 1, "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deliveries.insert_one(doc)
    return did


def _ensure_vip_courier():
    _db().users.update_one({"user_id": VIP_ID}, {"$set": {"is_courier": True}})


def _get(status=None, **params):
    if status:
        params["status"] = status
    return requests.get(f"{API}/admin/deliveries", headers=_hdr(ADMIN_TOKEN),
                        params=params, timeout=15)


def test_active_excludes_delivered_pending_and_history():
    acc = _mk(status="accepted", courier_id=VIP_ID, courier_name="VIP")
    deliv = _mk(status="delivered", courier_id=VIP_ID, courier_name="VIP")
    conf = _mk(status="confirmed", courier_id=VIP_ID, courier_name="VIP")
    cxl = _mk(status="cancelled")
    try:
        ids = {d["id"] for d in _get("active").json()}
        assert acc in ids
        assert deliv not in ids   # entregada -> pendiente de confirmación
        assert conf not in ids
        assert cxl not in ids
    finally:
        _db().deliveries.delete_many({"id": {"$in": [acc, deliv, conf, cxl]}})


def test_pending_confirmation_returns_only_delivered():
    acc = _mk(status="accepted", courier_id=VIP_ID, courier_name="VIP")
    deliv = _mk(status="delivered", courier_id=VIP_ID, courier_name="VIP")
    conf = _mk(status="confirmed", courier_id=VIP_ID, courier_name="VIP")
    try:
        ids = {d["id"] for d in _get("pending_confirmation").json()}
        assert deliv in ids
        assert acc not in ids
        assert conf not in ids
    finally:
        _db().deliveries.delete_many({"id": {"$in": [acc, deliv, conf]}})


def test_server_pagination_and_total_count_header():
    made = [_mk(status="confirmed", courier_id=VIP_ID, courier_name="VIP")
            for _ in range(5)]
    try:
        r = _get("history", limit=2, skip=0)
        assert r.status_code == 200, r.text
        assert "x-total-count" in {k.lower() for k in r.headers}
        total = int(r.headers["X-Total-Count"])
        assert total >= 5
        page1 = r.json()
        assert len(page1) == 2
        page2 = _get("history", limit=2, skip=2).json()
        assert len(page2) == 2
        # páginas distintas (sin solapamiento)
        assert {d["id"] for d in page1}.isdisjoint({d["id"] for d in page2})
    finally:
        _db().deliveries.delete_many({"id": {"$in": made}})


def test_courier_history_endpoint_full_and_paginated():
    _ensure_vip_courier()
    made = [_mk(status="confirmed", courier_id=VIP_ID, courier_name="VIP")
            for _ in range(3)]
    made.append(_mk(status="cancelled", courier_id=VIP_ID, courier_name="VIP"))
    try:
        r = requests.get(f"{API}/courier/deliveries/history",
                         headers=_hdr(VIP_TOKEN),
                         params={"limit": 2, "skip": 0}, timeout=15)
        assert r.status_code == 200, r.text
        total = int(r.headers["X-Total-Count"])
        assert total >= 4   # incluye confirmed + cancelled del mensajero
        assert len(r.json()) == 2
        # segunda página
        r2 = requests.get(f"{API}/courier/deliveries/history",
                          headers=_hdr(VIP_TOKEN),
                          params={"limit": 2, "skip": 2}, timeout=15)
        assert len(r2.json()) >= 1
    finally:
        _db().deliveries.delete_many({"id": {"$in": made}})
