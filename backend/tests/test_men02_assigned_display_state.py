"""MEN-02 — Estado derivado «ASIGNADA» (reservada, pendiente de aceptación).

Antes, al reservar una entrega para un mensajero quedaba `status=available`
con `courier_id` vacío: el filtro admin «available» la seguía devolviendo y la
tabla la mostraba como DISPONIBLE, sin el destinatario. Ahora:
- Se EXCLUYE de los trabajos libres (`?status=available` y `available_count`).
- Se muestra como `display_status=assigned` con el nombre del destinatario.
- Aparece en el filtro `?status=assigned` y en `assigned_count`.
- Vuelve a `available` SOLO tras el rechazo (o liberación autorizada).
- Se conserva el bloqueo de aceptación por un tercero.
- Reservas ANTIGUAS sin `assigned_to_courier_name` resuelven el nombre al vuelo.
"""
import os
import uuid
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN

API = f"{BASE_URL}/api"
VIP_ID = "user_test_vip01"


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mk_delivery(**extra):
    """Inserta una entrega `available` libre directamente en la BD."""
    did = f"men02_{uuid.uuid4().hex[:10]}"
    doc = {
        "id": did, "status": "available", "kind": "withdrawal",
        "ref_id": uuid.uuid4().hex, "client_name": "MEN02 Cliente",
        "amount_label": "100 USDT", "address": "Calle Falsa 123",
        "km": 2, "fee_usdt": 5, "courier_share_usdt": 4,
        "platform_share_usdt": 1, "courier_id": None, "courier_name": None,
        "created_at": _now(), "updated_at": _now(),
    }
    doc.update(extra)
    _db().deliveries.insert_one(doc)
    return did


def _ensure_vip_courier():
    _db().users.update_one({"user_id": VIP_ID}, {"$set": {"is_courier": True}})
    u = _db().users.find_one({"user_id": VIP_ID}, {"_id": 0, "name": 1, "email": 1})
    return (u or {}).get("name") or (u or {}).get("email")


def _list(status=None):
    params = {"status": status} if status else {}
    r = requests.get(f"{API}/admin/deliveries", headers=_hdr(ADMIN_TOKEN),
                     params=params, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(rows):
    return {d["id"] for d in rows}


def test_assigned_delivery_is_excluded_from_available_and_shown_as_assigned():
    vip_name = _ensure_vip_courier()
    did = _mk_delivery()
    try:
        # Reservar para el VIP (mensajero).
        r = requests.post(f"{API}/admin/deliveries/{did}/assign",
                          headers=_hdr(ADMIN_TOKEN),
                          json={"courier_id": VIP_ID}, timeout=15)
        assert r.status_code == 200, r.text

        # NO aparece en los trabajos libres.
        assert did not in _ids(_list("available"))

        # Aparece en el filtro «assigned» con estado derivado + destinatario.
        assigned = [d for d in _list("assigned") if d["id"] == did]
        assert len(assigned) == 1
        d = assigned[0]
        assert d["display_status"] == "assigned"
        assert d.get("assigned_to_courier_id") == VIP_ID
        assert d.get("assigned_to_courier_name") == vip_name

        # En «Todas» también sale marcada como assigned.
        allrows = [d for d in _list(None) if d["id"] == did]
        assert allrows and allrows[0]["display_status"] == "assigned"
    finally:
        _db().deliveries.delete_one({"id": did})


def test_summary_splits_available_and_assigned_counts():
    _ensure_vip_courier()
    did = _mk_delivery()
    try:
        before = requests.get(f"{API}/admin/deliveries/summary",
                              headers=_hdr(ADMIN_TOKEN)).json()
        requests.post(f"{API}/admin/deliveries/{did}/assign",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"courier_id": VIP_ID}, timeout=15)
        after = requests.get(f"{API}/admin/deliveries/summary",
                             headers=_hdr(ADMIN_TOKEN)).json()
        assert "assigned_count" in after
        # Al reservar, sube asignadas y no cuenta como libre.
        assert after["assigned_count"] >= before.get("assigned_count", 0) + 1
    finally:
        _db().deliveries.delete_one({"id": did})


def test_third_party_cannot_accept_reserved_delivery():
    _ensure_vip_courier()
    did = _mk_delivery()
    try:
        requests.post(f"{API}/admin/deliveries/{did}/assign",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"courier_id": VIP_ID}, timeout=15)
        # El empleado (otro mensajero) NO puede aceptarla.
        r = requests.post(f"{API}/courier/deliveries/{did}/claim",
                          headers=_hdr(EMPLOYEE_TOKEN), timeout=15)
        assert r.status_code == 403, r.text
    finally:
        _db().deliveries.delete_one({"id": did})


def test_reject_returns_delivery_to_available():
    _ensure_vip_courier()
    did = _mk_delivery()
    try:
        requests.post(f"{API}/admin/deliveries/{did}/assign",
                      headers=_hdr(ADMIN_TOKEN),
                      json={"courier_id": VIP_ID}, timeout=15)
        # ABA (A08) — el rechazo se ata a la identidad de la asignación mostrada.
        uid = _db().deliveries.find_one({"id": did}, {"_id": 0}).get(
            "assignment_uid")
        # El mensajero reservado rechaza → vuelve a libre.
        r = requests.post(f"{API}/courier/deliveries/{did}/reject-reservation",
                          headers=_hdr(VIP_TOKEN),
                          json={"reason": "No puedo ahora mismo",
                                "assignment_uid": uid}, timeout=15)
        assert r.status_code == 200, r.text
        assert did in _ids(_list("available"))
        assert did not in _ids(_list("assigned"))
        d = [x for x in _list(None) if x["id"] == did][0]
        assert d["display_status"] == "available"
    finally:
        _db().deliveries.delete_one({"id": did})


def test_legacy_reservation_without_name_resolves_destinatario():
    vip_name = _ensure_vip_courier()
    # Reserva «antigua»: assigned_to_courier_id pero SIN assigned_to_courier_name.
    did = _mk_delivery(assigned_to_courier_id=VIP_ID)
    try:
        d = [x for x in _list("assigned") if x["id"] == did][0]
        assert d["display_status"] == "assigned"
        assert d.get("assigned_to_courier_name") == vip_name
    finally:
        _db().deliveries.delete_one({"id": did})
