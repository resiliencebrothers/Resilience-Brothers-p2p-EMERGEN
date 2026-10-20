# Iter368 — Alta Empresa unificada (POST /company-signup → admin approve → gate email → verify → login)
import os
import uuid
import base64
import random
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
BYPASS = os.environ.get("TURNSTILE_TEST_BYPASS")
ADMIN = {"session_token": "test_session_admin_X"}
PNG = "data:image/png;base64," + base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()

mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
STATE = {}


def _email():
    return f"qa.iter368.{uuid.uuid4().hex[:8]}@gmail.com"


def _phone():
    return "+1555" + "".join(random.choice("0123456789") for _ in range(7))


def _payload(email, phone):
    return {"company_name": "TEST_QA Empresa SA", "account_email": email,
            "password": "Passw0rd!QA", "password_confirm": "Passw0rd!QA",
            "company_phone": phone, "tax_id": "TAX-12345",
            "address": "Calle Falsa 123, Ciudad", "operating_license": PNG,
            "legal_rep_id": PNG}


def _h():
    return {"X-Captcha-Bypass": BYPASS}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    emails = STATE.get("emails", [])
    uids = [u["user_id"] for u in mdb.users.find({"email": {"$in": emails}}, {"user_id": 1})]
    mdb.company_requests.delete_many({"account_email": {"$in": emails}})
    mdb.kyc_verifications.delete_many({"user_id": {"$in": uids}})
    mdb.user_sessions.delete_many({"user_id": {"$in": uids}})
    mdb.notifications.delete_many({"user_id": {"$in": uids}})
    mdb.users.delete_many({"user_id": {"$in": uids}})


class TestUnifiedCompanySignup:
    def test_captcha_required_without_bypass(self):
        # conftest injects the bypass header globally → override with a wrong value
        email = _email(); STATE.setdefault("emails", []).append(email)
        r = requests.post(f"{BASE_URL}/api/company-signup", json=_payload(email, _phone()),
                          headers={"X-Captcha-Bypass": "wrong"})
        assert r.status_code == 400, r.text
        assert "CAPTCHA_REQUIRED" in r.text

    def test_mismatch_password_422(self):
        p = _payload(_email(), _phone()); p["password_confirm"] = "OtherPass99"
        r = requests.post(f"{BASE_URL}/api/company-signup", json=p, headers=_h())
        assert r.status_code == 422

    def test_invalid_doc_422(self):
        p = _payload(_email(), _phone()); p["legal_rep_id"] = "notadataurl"
        r = requests.post(f"{BASE_URL}/api/company-signup", json=p, headers=_h())
        assert r.status_code == 422

    def test_signup_creates_pending_without_user(self):
        email, phone = _email(), _phone()
        STATE.setdefault("emails", []).append(email)
        STATE.update(email=email, phone=phone)
        r = requests.post(f"{BASE_URL}/api/company-signup", json=_payload(email, phone), headers=_h())
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        req = mdb.company_requests.find_one({"account_email": email})
        assert req and req["status"] == "pending"
        assert req.get("requester_anonymous") is True
        assert len(req["documents"]) == 2
        assert {d["doc_type"] for d in req["documents"]} == {"operating_license", "legal_rep_id"}
        assert req.get("password_hash")
        assert mdb.users.find_one({"email": email}) is None
        STATE["req_id"] = req["id"]

    def test_duplicate_pending_409(self):
        r = requests.post(f"{BASE_URL}/api/company-signup",
                          json=_payload(STATE["email"], _phone()), headers=_h())
        assert r.status_code == 409

    def test_admin_list_has_docs_and_no_hash(self):
        r = requests.get(f"{BASE_URL}/api/admin/company-requests?status=pending", cookies=ADMIN)
        assert r.status_code == 200
        it = next(i for i in r.json()["items"] if i["id"] == STATE["req_id"])
        assert "password_hash" not in it
        assert len(it["documents"]) == 2

    def test_doc_ref_accessible_by_admin(self):
        req = mdb.company_requests.find_one({"id": STATE["req_id"]})
        ref = req["documents"][0]["ref"]
        url = ref if ref.startswith("http") else f"{BASE_URL}{ref}"
        r = requests.get(url, cookies=ADMIN)
        assert r.status_code == 200, f"{ref} -> {r.status_code}"
        r2 = requests.get(url)
        assert r2.status_code in (401, 403), f"anon doc access {r2.status_code}"

    def test_approve_creates_active_company(self):
        rid = STATE["req_id"]
        r = requests.post(f"{BASE_URL}/api/admin/company-requests/{rid}/approve", cookies=ADMIN)
        assert r.status_code == 200, r.text
        u = mdb.users.find_one({"email": STATE["email"]})
        assert u["role"] == "empresa"
        assert u["account_status"] == "active"
        assert u["phone_verified"] is True
        assert u["email_verified"] is False
        assert u.get("kyc_status") == "verified"
        k = mdb.kyc_verifications.find_one({"user_id": u["user_id"], "kind": "company"})
        assert k and k["status"] == "verified"
        req = mdb.company_requests.find_one({"id": rid})
        assert req["status"] == "approved" and "password_hash" not in req
        STATE["token"] = u["verification_token"]

    def test_login_blocked_until_email_verified(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", headers=_h(),
                          json={"email": STATE["email"], "password": "Passw0rd!QA"})
        assert r.status_code in (401, 403), r.text
        assert "EMAIL_NOT_VERIFIED" in r.text

    def test_verify_email_then_login_ok(self):
        r = requests.get(f"{BASE_URL}/api/auth/verify-email/{STATE['token']}", allow_redirects=False)
        assert r.status_code in (200, 302, 303, 307), r.text
        assert mdb.users.find_one({"email": STATE["email"]})["email_verified"] is True
        r = requests.post(f"{BASE_URL}/api/auth/login", headers=_h(),
                          json={"email": STATE["email"], "password": "Passw0rd!QA"})
        assert r.status_code == 200, r.text
        body = r.json()
        user = body.get("user", body)
        assert user["role"] == "empresa"
        assert user["account_status"] == "active"

    def test_signup_existing_user_email_409(self):
        r = requests.post(f"{BASE_URL}/api/company-signup",
                          json=_payload(STATE["email"], _phone()), headers=_h())
        assert r.status_code == 409
