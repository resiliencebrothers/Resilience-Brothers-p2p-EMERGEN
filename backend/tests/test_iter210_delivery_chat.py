"""iter210 — Chat en la app cliente ↔ mensajero durante la entrega.

Verifica:
1. Cliente y mensajero pueden escribirse en una entrega activa.
2. Un tercero (no participante, sin permisos) recibe 403.
3. El chat queda cerrado (409 al enviar) cuando la entrega está confirmada.
4. /vip/deliveries/track expone `chat_unread` y GET del chat marca leído.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, NORMAL_TOKEN, EMPLOYEE_TOKEN, VIP_TOKEN

API = f"{BASE_URL}/api"
CLIENT_ID = "user_test_normal01"
COURIER_ID = "user_test_employee01"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _seed(status="accepted"):
    did = f"test210_{uuid.uuid4().hex[:10]}"
    _db().deliveries.insert_one({
        "id": did, "kind": "withdrawal", "ref_id": f"ref_{did}",
        "user_id": CLIENT_ID, "client_name": "Cliente 210",
        "address": "Calle W", "province": "La Habana",
        "amount_label": "800 CUP",
        "km": 2.0, "fee_usdt": 2.0, "share_pct_snapshot": 80.0,
        "courier_share_usdt": 1.6, "platform_share_usdt": 0.4,
        "status": status,
        "courier_id": COURIER_ID, "courier_name": "Empleado Test",
        "created_at": "2026-08-15T10:00:00+00:00",
        "updated_at": "2026-08-15T10:10:00+00:00",
        "timeline": [{"status": status, "at": "2026-08-15T10:10:00+00:00"}],
    })
    return did


def _cleanup(did):
    _db().deliveries.delete_many({"id": did})
    _db().delivery_chat.delete_many({"delivery_id": did})


def test_client_and_courier_can_chat_and_unread_tracks():
    did = _seed("accepted")
    try:
        # 1) Cliente envía
        r = requests.post(f"{API}/deliveries/{did}/chat",
                          headers=_hdr(NORMAL_TOKEN),
                          json={"text": "Hola, ¿a qué hora llegas?"})
        assert r.status_code == 200, r.text
        assert r.json()["sender_kind"] == "client"

        # 2) Mensajero lo ve y puede responder
        r = requests.get(f"{API}/deliveries/{did}/chat", headers=_hdr(EMPLOYEE_TOKEN))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["my_kind"] == "courier"
        assert body["can_send"] is True
        assert len(body["messages"]) == 1
        assert body["messages"][0]["text"] == "Hola, ¿a qué hora llegas?"

        r = requests.post(f"{API}/deliveries/{did}/chat",
                          headers=_hdr(EMPLOYEE_TOKEN),
                          json={"text": "En 20 minutos estoy ahí."})
        assert r.status_code == 200, r.text

        # 3) chat_unread del cliente en el tracker = 1 (respuesta sin leer)
        r = requests.get(f"{API}/vip/deliveries/track", headers=_hdr(NORMAL_TOKEN))
        assert r.status_code == 200, r.text
        item = next(i for i in r.json()["items"] if i["id"] == did)
        assert item["chat_unread"] == 1

        # 4) Al abrir el chat (GET) se marca leído → unread vuelve a 0
        r = requests.get(f"{API}/deliveries/{did}/chat", headers=_hdr(NORMAL_TOKEN))
        assert r.status_code == 200
        assert len(r.json()["messages"]) == 2
        r = requests.get(f"{API}/vip/deliveries/track", headers=_hdr(NORMAL_TOKEN))
        item = next(i for i in r.json()["items"] if i["id"] == did)
        assert item["chat_unread"] == 0
    finally:
        _cleanup(did)


def test_third_party_forbidden_and_validation():
    did = _seed("accepted")
    try:
        # VIP no participa (no es cliente ni mensajero de ESTA entrega)
        r = requests.get(f"{API}/deliveries/{did}/chat", headers=_hdr(VIP_TOKEN))
        assert r.status_code == 403, r.text
        r = requests.post(f"{API}/deliveries/{did}/chat",
                          headers=_hdr(VIP_TOKEN), json={"text": "hola"})
        assert r.status_code == 403, r.text
        # texto vacío
        r = requests.post(f"{API}/deliveries/{did}/chat",
                          headers=_hdr(NORMAL_TOKEN), json={"text": "   "})
        assert r.status_code == 400
        # texto demasiado largo
        r = requests.post(f"{API}/deliveries/{did}/chat",
                          headers=_hdr(NORMAL_TOKEN), json={"text": "x" * 501})
        assert r.status_code == 400
    finally:
        _cleanup(did)


def test_chat_closed_after_confirmed():
    did = _seed("confirmed")
    try:
        r = requests.get(f"{API}/deliveries/{did}/chat", headers=_hdr(NORMAL_TOKEN))
        assert r.status_code == 200
        assert r.json()["can_send"] is False
        r = requests.post(f"{API}/deliveries/{did}/chat",
                          headers=_hdr(NORMAL_TOKEN), json={"text": "hola"})
        assert r.status_code == 409, r.text
    finally:
        _cleanup(did)
