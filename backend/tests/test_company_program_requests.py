"""Programa Empresas — solicitud de alta de una cuenta Empresa independiente.

Flujo nuevo (jun 2026): un cliente (normal/vip) solicita desde su perfil crear
una cuenta Empresa NUEVA e independiente (email+contraseña propios). Al aprobar,
Resilience crea esa cuenta `empresa` (under_review) SIN tocar la cuenta personal.

Usa el usuario VIP sembrado como solicitante y el EMPLEADO (permisos vacíos =
todos) como revisor, de modo que la suite funcione con los fixtures estándar.

Cubre: envío (cliente), validaciones, unicidad, una pendiente a la vez,
aprobación (crea cuenta nueva, copia hash bcrypt, borra hash de la solicitud,
no cambia el rol personal), rechazo + enfriamiento, y gates de permiso.
"""
import os
import uuid

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, EMPLOYEE_TOKEN, VIP_TOKEN, ADMIN_TOKEN, make_admin_totp

API = f"{BASE_URL}/api"

CLIENT_TOKEN = VIP_TOKEN                 # solicitante (rol vip, existe sembrado)
CLIENT_UID = "user_test_vip01"
STAFF_TOKEN = EMPLOYEE_TOKEN             # revisor (permisos vacíos = todos)


def _h(tok):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _rand_email():
    return f"empresa_{uuid.uuid4().hex[:10]}@mibodega.com"


def _rand_phone():
    return "+1" + "".join(str(int(c, 16) % 10) for c in uuid.uuid4().hex[:10])


def _payload(**over):
    body = {
        "company_name": "Distribuidora Test S.A.",
        "account_email": _rand_email(),
        "password": "CompanyPass123!",
        "password_confirm": "CompanyPass123!",
        "company_phone": _rand_phone(),
        "tax_id": "RNC-123456789",
        "address": "Calle 23 #456, Vedado, La Habana",
    }
    body.update(over)
    return body


class TestCompanyProgramRequests:
    def setup_method(self, _):
        self._emails = set()
        self._req_ids = set()
        _db().company_requests.delete_many({"user_id": CLIENT_UID})

    def teardown_method(self, _):
        db = _db()
        db.company_requests.delete_many({"user_id": CLIENT_UID})
        if self._req_ids:
            db.company_requests.delete_many({"id": {"$in": list(self._req_ids)}})
        # Solo borra cuentas Empresa creadas por ESTE flujo (nunca usuarios
        # sembrados: estos no tienen parent_user_id == CLIENT_UID).
        if self._emails:
            db.users.delete_many(
                {"email": {"$in": list(self._emails)}, "parent_user_id": CLIENT_UID})
        db.notifications.delete_many(
            {"recipient_user_id": CLIENT_UID, "type": "company_account_activated"})

    def _submit(self, tok, **over):
        body = _payload(**over)
        self._emails.add(body["account_email"].lower())
        r = requests.post(f"{API}/company-requests", headers=_h(tok), json=body)
        if r.status_code == 200:
            self._req_ids.add(r.json()["id"])
        return r, body

    # ---------- envío (cliente) ----------

    def test_client_can_submit_and_hash_never_leaks(self):
        r, body = self._submit(CLIENT_TOKEN)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "pending"
        assert data["account_email"] == body["account_email"].lower()
        assert data["company_name"] == body["company_name"]
        assert "password_hash" not in data and "password" not in data
        doc = _db().company_requests.find_one({"id": data["id"]})
        assert doc and doc.get("password_hash")
        from auth_utils import _verify_password
        assert _verify_password("CompanyPass123!", doc["password_hash"])

    def test_staff_cannot_submit(self):
        r, _ = self._submit(STAFF_TOKEN)
        assert r.status_code == 403, r.text

    def test_password_mismatch_rejected(self):
        r, _ = self._submit(CLIENT_TOKEN, password_confirm="OtraClave999!")
        assert r.status_code == 422, r.text

    def test_company_email_must_differ_from_personal(self):
        personal = _db().users.find_one({"user_id": CLIENT_UID}, {"email": 1})["email"]
        r, _ = self._submit(CLIENT_TOKEN, account_email=personal)
        assert r.status_code == 409, r.text

    def test_email_in_use_rejected(self):
        staff_email = _db().users.find_one(
            {"user_id": "user_test_employee01"}, {"email": 1})["email"]
        r, _ = self._submit(CLIENT_TOKEN, account_email=staff_email)
        assert r.status_code == 409, r.text

    def test_one_pending_at_a_time(self):
        r1, _ = self._submit(CLIENT_TOKEN)
        assert r1.status_code == 200, r1.text
        r2, _ = self._submit(CLIENT_TOKEN)
        assert r2.status_code == 409, r2.text

    def test_me_reflects_state(self):
        r, _ = self._submit(CLIENT_TOKEN)
        assert r.status_code == 200
        me = requests.get(f"{API}/company-requests/me", headers=_h(CLIENT_TOKEN))
        assert me.status_code == 200, me.text
        mb = me.json()
        assert mb["request"]["id"] == r.json()["id"]
        assert mb["can_submit"] is False
        assert "password_hash" not in mb["request"]

    # ---------- staff: aprobación ----------

    def test_approve_creates_independent_account(self):
        r, body = self._submit(CLIENT_TOKEN)
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]

        lst = requests.get(f"{API}/admin/company-requests",
                           headers=_h(STAFF_TOKEN), params={"status": "pending"})
        assert lst.status_code == 200, lst.text
        assert any(it["id"] == req_id for it in lst.json()["items"])
        assert all("password_hash" not in it for it in lst.json()["items"])

        ap = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert ap.status_code == 200, ap.text
        assert ap.json()["status"] == "approved"

        db = _db()
        acc = db.users.find_one({"email": body["account_email"].lower()})
        assert acc is not None
        assert acc["role"] == "empresa"
        assert acc["account_status"] == "under_review"
        assert acc["email_verified"] is False
        assert acc.get("parent_user_id") == CLIENT_UID
        from auth_utils import _verify_password
        assert _verify_password("CompanyPass123!", acc["password_hash"])

        # la cuenta personal NO cambió de rol
        personal = db.users.find_one({"user_id": CLIENT_UID})
        assert personal["role"] == "vip"

        req_doc = db.company_requests.find_one({"id": req_id})
        assert req_doc["status"] == "approved"
        assert req_doc.get("new_user_id") == acc["user_id"]
        assert "password_hash" not in req_doc

    def test_approve_twice_is_idempotent_conflict(self):
        r, _ = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        a1 = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert a1.status_code == 200, a1.text
        a2 = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert a2.status_code == 409, a2.text

    def test_approve_then_reject_conflicts_and_keeps_account(self):
        r, body = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        ap = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert ap.status_code == 200, ap.text
        rj = requests.post(f"{API}/admin/company-requests/{req_id}/reject",
                           headers=_h(STAFF_TOKEN), json={"admin_note": "tarde"})
        assert rj.status_code == 409, rj.text
        db = _db()
        fresh = db.company_requests.find_one({"id": req_id})
        assert fresh["status"] == "approved"          # el rechazo NO pisó nada
        assert db.users.find_one({"email": body["account_email"].lower()}) is not None

    def test_reject_then_approve_conflicts_no_account(self):
        r, body = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        rj = requests.post(f"{API}/admin/company-requests/{req_id}/reject",
                           headers=_h(STAFF_TOKEN), json={"admin_note": "no"})
        assert rj.status_code == 200, rj.text
        ap = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert ap.status_code == 409, ap.text
        db = _db()
        assert db.company_requests.find_one({"id": req_id})["status"] == "rejected"
        # el aprobador perdedor NO creó cuenta (CAS antes del insert)
        assert db.users.find_one({"email": body["account_email"].lower()}) is None

    def test_two_rejects_conflict(self):
        r, _ = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        r1 = requests.post(f"{API}/admin/company-requests/{req_id}/reject",
                           headers=_h(STAFF_TOKEN), json={"admin_note": "a"})
        assert r1.status_code == 200, r1.text
        r2 = requests.post(f"{API}/admin/company-requests/{req_id}/reject",
                           headers=_h(STAFF_TOKEN), json={"admin_note": "b"})
        assert r2.status_code == 409, r2.text

    # ---------- staff: rechazo + enfriamiento ----------

    def test_reject_sets_note_and_cooldown(self):
        r, _ = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        rj = requests.post(f"{API}/admin/company-requests/{req_id}/reject",
                           headers=_h(STAFF_TOKEN), json={"admin_note": "Faltan datos fiscales."})
        assert rj.status_code == 200, rj.text
        assert rj.json()["status"] == "rejected"
        assert rj.json()["admin_note"] == "Faltan datos fiscales."
        assert "password_hash" not in _db().company_requests.find_one({"id": req_id})
        r2, _ = self._submit(CLIENT_TOKEN)
        assert r2.status_code == 429, r2.text
        me = requests.get(f"{API}/company-requests/me", headers=_h(CLIENT_TOKEN)).json()
        assert me["cooldown_days_left"] > 0

    # ---------- gates de permiso ----------

    def test_non_staff_cannot_access_admin_endpoints(self):
        r = requests.get(f"{API}/admin/company-requests", headers=_h(CLIENT_TOKEN))
        assert r.status_code in (401, 403), r.text
        pc = requests.get(f"{API}/admin/company-requests/pending-count",
                          headers=_h(CLIENT_TOKEN))
        assert pc.status_code in (401, 403), pc.text

    def test_pending_count_for_staff(self):
        before = requests.get(f"{API}/admin/company-requests/pending-count",
                              headers=_h(STAFF_TOKEN)).json()["pending"]
        self._submit(CLIENT_TOKEN)
        after = requests.get(f"{API}/admin/company-requests/pending-count",
                             headers=_h(STAFF_TOKEN)).json()["pending"]
        assert after == before + 1

    def test_pending_counts_includes_company_requests(self):
        before = requests.get(f"{API}/admin/pending-counts",
                              headers=_h(STAFF_TOKEN)).json().get("company_requests", 0)
        self._submit(CLIENT_TOKEN)
        after = requests.get(f"{API}/admin/pending-counts",
                             headers=_h(STAFF_TOKEN)).json()["company_requests"]
        assert after == before + 1

    def test_me_shows_company_account_kyb_after_approval(self):
        r, body = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        ap = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert ap.status_code == 200, ap.text
        me = requests.get(f"{API}/company-requests/me", headers=_h(CLIENT_TOKEN)).json()
        assert me["request"]["status"] == "approved"
        acc = me["company_account"]
        assert acc is not None
        assert acc["account_status"] == "under_review"
        assert acc["phone_verified"] is False
        assert acc["email_verified"] is False

    # ---------- reenvío de verificación de la cuenta Empresa ----------

    def test_resend_verification_regenerates_and_cooldown(self):
        r, body = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        ap = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert ap.status_code == 200, ap.text
        db = _db()
        before = db.users.find_one({"email": body["account_email"].lower()})["verification_token"]
        # primer reenvío OK → token regenerado
        rs = requests.post(f"{API}/company-requests/resend-verification",
                           headers=_h(CLIENT_TOKEN))
        assert rs.status_code == 200, rs.text
        assert rs.json()["status"] == "sent"
        after = db.users.find_one({"email": body["account_email"].lower()})["verification_token"]
        assert after and after != before
        # segundo reenvío inmediato → 429 (enfriamiento 60s)
        rs2 = requests.post(f"{API}/company-requests/resend-verification",
                            headers=_h(CLIENT_TOKEN))
        assert rs2.status_code == 429, rs2.text

    def test_resend_without_approved_account_404(self):
        rs = requests.post(f"{API}/company-requests/resend-verification",
                           headers=_h(CLIENT_TOKEN))
        assert rs.status_code == 404, rs.text

    def test_resend_already_verified_returns_status(self):
        r, body = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        requests.post(f"{API}/admin/company-requests/{req_id}/approve", headers=_h(STAFF_TOKEN))
        # marcar email verificado directamente
        _db().users.update_one({"email": body["account_email"].lower()},
                               {"$set": {"email_verified": True}})
        rs = requests.post(f"{API}/company-requests/resend-verification",
                           headers=_h(CLIENT_TOKEN))
        assert rs.status_code == 200, rs.text
        assert rs.json()["status"] == "already_verified"

    # ---------- aviso al solicitante al activarse la cuenta Empresa ----------

    def test_activation_notifies_requester(self):
        r, body = self._submit(CLIENT_TOKEN)
        req_id = r.json()["id"]
        ap = requests.post(f"{API}/admin/company-requests/{req_id}/approve",
                           headers=_h(STAFF_TOKEN))
        assert ap.status_code == 200, ap.text
        empresa_uid = ap.json()["new_user_id"]
        # staff verifica el teléfono → cuenta pasa a active (requiere TOTP step-up)
        vp = requests.post(
            f"{API}/admin/users/{empresa_uid}/verify-phone",
            headers=_h(ADMIN_TOKEN), json={"totp_code": make_admin_totp()},
        )
        assert vp.status_code == 200, vp.text
        # el SOLICITANTE recibe notificación de activación
        note = _db().notifications.find_one(
            {"recipient_user_id": CLIENT_UID, "type": "company_account_activated"})
        assert note is not None
        assert note["data"].get("company_user_id") == empresa_uid
        # /me ahora refleja la cuenta Empresa activa
        me = requests.get(f"{API}/company-requests/me", headers=_h(CLIENT_TOKEN)).json()
        assert me["company_account"]["account_status"] == "active"
        assert me["company_account"]["phone_verified"] is True
