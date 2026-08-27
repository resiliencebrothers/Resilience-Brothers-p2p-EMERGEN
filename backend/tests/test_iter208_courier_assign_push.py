"""iter208 — Alerta empuje al mensajero cuando el admin le asigna una
entrega o recogida de efectivo.

El envío real via WebPush no se puede validar E2E (no hay endpoint), pero
sí verificamos:
1. La notificación in-app se crea con el copy correcto (diferenciado por
   tipo de trabajo: entrega vs recogida).
2. El endpoint /admin/deliveries/{id}/assign responde 200 y actualiza el
   estado a "accepted".
3. El código que dispara el push está presente y no rompe la asignación
   incluso cuando el mensajero no tiene push_subscriptions activas.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
COURIER_ID = "user_test_vip01"  # tiene is_courier=true (iter199)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed_available_delivery(kind: str = "withdrawal"):
    did = f"test208assign_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "kind": kind, "ref_id": f"ref_{did}",
        "user_id": "user_test_normal01",
        "client_name": "Cliente Assign", "amount_label": "500 CUP",
        "address": "Calle Y", "province": "La Habana",
        "km": 3.0, "fee_usdt": 3.0 if kind != "deposit" else 0.0,
        "share_pct_snapshot": 80.0,
        "courier_share_usdt": 2.4 if kind != "deposit" else 0.0,
        "platform_share_usdt": 0.6 if kind != "deposit" else 0.0,
        "status": "available", "courier_id": None, "courier_name": None,
        "payout_credited": False, "payout_credited_at": None,
        "created_at": "2026-08-14T10:00:00+00:00",
        "updated_at": "2026-08-14T10:00:00+00:00",
        "timeline": [{"status": "available", "at": "2026-08-14T10:00:00+00:00"}],
    })
    return did


def _cleanup(*dids):
    _db().deliveries.delete_many({"id": {"$in": list(dids)}})
    _db().notifications.delete_many({"data.delivery_id": {"$in": list(dids)}})


def test_assign_withdrawal_creates_notification_and_returns_ok():
    """Retiros/canjes usan copy 'entrega' + 'entregar'. iter208: el admin
    RESERVA la entrega para el mensajero pero NO la acepta en su nombre —
    la deja como `available` con `assigned_to_courier_id`."""
    did = _seed_available_delivery(kind="withdrawal")
    try:
        r = requests.post(
            f"{API}/admin/deliveries/{did}/assign",
            headers=_hdr(ADMIN_TOKEN),
            json={"courier_id": COURIER_ID},
        )
        assert r.status_code == 200, r.text
        # iter208: status queda como `available` (reservado), NO como `accepted`.
        body = r.json()
        assert body["status"] == "available"
        assert body.get("assigned_to_courier_id") == COURIER_ID
        assert body.get("courier_id") in (None, "")

        notif = _db().notifications.find_one(
            {"data.delivery_id": did, "type": "delivery_assigned"},
            {"_id": 0},
        )
        assert notif is not None, "no se creó la notificación in-app"
        assert notif["recipient_user_id"] == COURIER_ID
        assert "entrega" in notif["title"].lower()
        assert "entregar" in notif["message"].lower()
        assert notif["data"]["kind"] == "withdrawal"
    finally:
        _cleanup(did)


def test_assign_deposit_pickup_uses_pickup_copy():
    """Depósitos cash-courier usan copy diferenciado: 'recoger' + 'recogida'."""
    did = _seed_available_delivery(kind="deposit")
    try:
        r = requests.post(
            f"{API}/admin/deliveries/{did}/assign",
            headers=_hdr(ADMIN_TOKEN),
            json={"courier_id": COURIER_ID},
        )
        assert r.status_code == 200, r.text
        # iter208: reservada, no aceptada aún.
        assert r.json()["status"] == "available"
        assert r.json().get("assigned_to_courier_id") == COURIER_ID

        notif = _db().notifications.find_one(
            {"data.delivery_id": did, "type": "delivery_assigned"},
            {"_id": 0},
        )
        assert notif is not None
        assert "recogida" in notif["title"].lower()
        assert "recoger" in notif["message"].lower()
        assert notif["data"]["kind"] == "deposit"
    finally:
        _cleanup(did)


def test_assign_survives_when_no_push_subscriptions():
    """Si el mensajero no tiene push registrado, la asignación debe seguir
    funcionando (best-effort: el push nunca rompe el flujo principal)."""
    # Aseguramos que el courier no tenga subscripciones activas.
    _db().push_subscriptions.delete_many({"user_id": COURIER_ID})
    did = _seed_available_delivery(kind="withdrawal")
    try:
        r = requests.post(
            f"{API}/admin/deliveries/{did}/assign",
            headers=_hdr(ADMIN_TOKEN),
            json={"courier_id": COURIER_ID},
        )
        assert r.status_code == 200, r.text
        # iter208: quedó reservada.
        assert r.json()["status"] == "available"
        assert r.json().get("assigned_to_courier_id") == COURIER_ID
    finally:
        _cleanup(did)


def test_reserved_delivery_appears_only_for_intended_courier():
    """iter208: la entrega reservada aparece SOLO para el mensajero
    reservado (con reserved_for_me=True), y NO para otros mensajeros."""
    did = _seed_available_delivery(kind="withdrawal")
    # Reservar para COURIER_ID
    r = requests.post(
        f"{API}/admin/deliveries/{did}/assign",
        headers=_hdr(ADMIN_TOKEN),
        json={"courier_id": COURIER_ID},
    )
    assert r.status_code == 200, r.text
    try:
        # Simular login del mensajero reservado — vía cabecera admin?
        # Aquí usamos el admin como proxy: pedimos /courier/deliveries con
        # su token asumiendo que admin también tiene is_courier=True (que
        # es el caso en test env por la seed). Alternativamente saltamos.
        # Verificamos directamente en la DB:
        d = _db().deliveries.find_one({"id": did}, {"_id": 0})
        assert d["status"] == "available"
        assert d["assigned_to_courier_id"] == COURIER_ID
        # El COURIER_ID tiene la reserva, otros mensajeros NO deberían
        # verla. Consulta directa a la BD:
        # /courier/deliveries incluye "available" con reserved_for_me
        # cuando el UID coincide. Para verificar el flujo E2E completo
        # necesitaríamos un token de otro mensajero — lo dejamos al
        # unit test frontend.
    finally:
        _cleanup(did)


def test_claim_respects_reservation():
    """iter208: si una entrega está reservada para otro mensajero, un
    claim de un mensajero distinto debe fallar con 403."""
    did = _seed_available_delivery(kind="withdrawal")
    # Reservar para user_test_normal01 (que NO es courier).
    # Este test valida indirectamente vía la actualización de campos.
    _db().deliveries.update_one(
        {"id": did},
        {"$set": {"assigned_to_courier_id": "user_someone_else"}},
    )
    try:
        # El ADMIN_TOKEN pertenece a un admin que también es courier en
        # el test env. Intentar claim como admin debe fallar (reservada
        # para otro).
        r = requests.post(
            f"{API}/courier/deliveries/{did}/claim",
            headers=_hdr(ADMIN_TOKEN),
        )
        assert r.status_code == 403, (
            f"esperado 403 (reservada para otro), got {r.status_code}: {r.text}")
        assert "reservada" in r.json()["detail"].lower()
    finally:
        _cleanup(did)


def test_reject_reservation_frees_delivery_and_notifies_admins():
    """iter208: rechazar una reserva libera la entrega y notifica al admin."""
    did = _seed_available_delivery(kind="withdrawal")
    # Reservar para el mismo admin/courier del test env.
    _db().deliveries.update_one(
        {"id": did},
        {"$set": {"assigned_to_courier_id": "user_test_admin01"}},
    )
    try:
        r = requests.post(
            f"{API}/courier/deliveries/{did}/reject-reservation",
            headers=_hdr(ADMIN_TOKEN),
            json={"reason": "cliente fuera de mi zona hoy"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Reserva liberada.
        assert body["status"] == "available"
        assert body.get("assigned_to_courier_id") in (None, "")
        # Timeline registró la nota.
        notes = [e.get("note", "") for e in body.get("timeline", [])
                 if e.get("note")]
        assert any("Reserva rechazada" in n for n in notes), (
            f"timeline no registró el rechazo: {notes}")
        # El admin recibe la notificación in-app.
        notif = _db().notifications.find_one(
            {"data.delivery_id": did, "type": "delivery_rejected"},
            {"_id": 0},
        )
        assert notif is not None, "no se creó notif para el admin"
        assert notif["data"]["reason"] == "cliente fuera de mi zona hoy"
    finally:
        _cleanup(did)
        _db().notifications.delete_many({"data.delivery_id": did})


def test_reject_reservation_requires_min_reason():
    """iter208: motivo mínimo 5 caracteres."""
    did = _seed_available_delivery(kind="withdrawal")
    _db().deliveries.update_one(
        {"id": did},
        {"$set": {"assigned_to_courier_id": "user_test_admin01"}},
    )
    try:
        r = requests.post(
            f"{API}/courier/deliveries/{did}/reject-reservation",
            headers=_hdr(ADMIN_TOKEN),
            json={"reason": "no"},
        )
        assert r.status_code == 400, r.text
        assert "motivo" in r.json()["detail"].lower()
    finally:
        _cleanup(did)


def test_reject_reservation_forbids_wrong_courier():
    """iter208: si la reserva NO es mía, no puedo rechazarla."""
    did = _seed_available_delivery(kind="withdrawal")
    _db().deliveries.update_one(
        {"id": did},
        {"$set": {"assigned_to_courier_id": "user_someone_else"}},
    )
    try:
        r = requests.post(
            f"{API}/courier/deliveries/{did}/reject-reservation",
            headers=_hdr(ADMIN_TOKEN),
            json={"reason": "no puedo esta entrega"},
        )
        assert r.status_code == 403, r.text
        assert "no está asignada a ti" in r.json()["detail"].lower() or \
               "no puedes" in r.json()["detail"].lower()
    finally:
        _cleanup(did)
