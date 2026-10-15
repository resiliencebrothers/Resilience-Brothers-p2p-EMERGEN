"""Incidencias de mensajería (admin) — listar entregas con origen incompatible
(origin_conflict) y marcarlas resueltas. Gestión manual."""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _mk_conflict(resolved=False, with_origin=True):
    did = str(uuid.uuid4())
    ref_id = str(uuid.uuid4())
    db = _db()
    if with_origin:
        db.redemptions.insert_one({
            "id": ref_id, "status": "cancelled", "product_name": "Café 1kg",
            "quantity": 2, "total_usd": 30, "user_name": "Ana",
            "user_email": "ana@x.com", "created_at": "2026-01-01T00:00:00+00:00"})
    oc = {"kind": "redemption", "ref_id": ref_id,
          "note": "origen rechazado", "at": "2026-01-01T00:00:00+00:00"}
    if resolved:
        oc["resolved"] = True
        oc["resolved_at"] = "2026-01-02T00:00:00+00:00"
        oc["resolution_note"] = "efectivo verificado"
    db.deliveries.insert_one({
        "id": did, "kind": "redemption", "ref_id": ref_id,
        "status": "delivered", "client_name": "Cliente X",
        "origin_conflict": oc, "created_at": "2026-01-01T00:00:00+00:00"})
    return did, ref_id


class TestDeliveryIncidents:
    def teardown_method(self, _):
        db = _db()
        db.deliveries.delete_many({"client_name": "Cliente X"})
        db.redemptions.delete_many({"user_name": "Ana"})

    def test_list_only_open_conflicts_with_origin(self):
        open_did, _ = _mk_conflict(resolved=False)
        done_did, _ = _mk_conflict(resolved=True)
        r = requests.get(f"{API}/admin/delivery-incidents", headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        rows = {d["id"]: d for d in r.json()}
        assert open_did in rows and done_did not in rows
        # cada fila trae el resumen del origen para gestión manual
        origin = rows[open_did].get("origin") or {}
        assert origin.get("product_name") == "Café 1kg"
        assert origin.get("status") == "cancelled"

    def test_resolved_history_view(self):
        done_did, _ = _mk_conflict(resolved=True)
        r = requests.get(f"{API}/admin/delivery-incidents",
                         params={"resolved": "true"}, headers=_h(ADMIN_TOKEN))
        assert r.status_code == 200, r.text
        ids = {d["id"] for d in r.json()}
        assert done_did in ids

    def test_resolve_closes_incident_idempotently(self):
        did, _ = _mk_conflict(resolved=False)
        r = requests.post(f"{API}/admin/delivery-incidents/{did}/resolve",
                          headers=_h(ADMIN_TOKEN), json={"note": "efectivo verificado"})
        assert r.status_code == 200, r.text
        d = _db().deliveries.find_one({"id": did}, {"_id": 0, "origin_conflict": 1})
        assert d["origin_conflict"]["resolved"] is True
        assert d["origin_conflict"]["resolution_note"] == "efectivo verificado"
        # ya no aparece en la lista de abiertas
        lst = requests.get(f"{API}/admin/delivery-incidents", headers=_h(ADMIN_TOKEN)).json()
        assert did not in {x["id"] for x in lst}
        # segundo resolve → 404 (idempotente; ya cerrada)
        r2 = requests.post(f"{API}/admin/delivery-incidents/{did}/resolve",
                           headers=_h(ADMIN_TOKEN), json={"note": "x"})
        assert r2.status_code == 404

    def test_non_admin_forbidden(self):
        r = requests.get(f"{API}/admin/delivery-incidents", headers=_h(NORMAL_TOKEN))
        assert r.status_code in (401, 403)
