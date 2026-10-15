"""Verificación de cuenta Empresa (KYC empresa): código fiscal + licencia
operativa + dirección. Distinto del KYC individual (identidad + selfie)."""
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"
EMP_ID = "user_test_empresa_kyc"
EMP_TOKEN = "test_session_empresa_kyc_X"

# 1x1 PNG en data URL (imagen mínima válida).
PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
       "QVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _seed():
    db = _db()
    db.users.update_one({"user_id": EMP_ID}, {"$set": {
        "user_id": EMP_ID, "email": "empresa.kyc@example.com", "name": "Empresa KYC",
        "role": "empresa", "account_status": "active", "account_type": "business",
        "email_verified": True, "phone_verified": True, "phone": "+5350000999",
        "kyc_status": "unverified"}}, upsert=True)
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    db.user_sessions.update_one({"session_token": EMP_TOKEN},
        {"$set": {"session_token": EMP_TOKEN, "user_id": EMP_ID, "expires_at": exp}},
        upsert=True)
    db.kyc_verifications.delete_many({"user_id": EMP_ID})


def _cleanup():
    db = _db()
    db.kyc_verifications.delete_many({"user_id": EMP_ID})


class TestCompanyKYC:
    def setup_method(self, _):
        _seed()

    def teardown_method(self, _):
        _cleanup()

    def test_company_submit_creates_company_verification(self):
        r = requests.post(f"{API}/kyc/company/submit", headers=_hdr(EMP_TOKEN), json={
            "fiscal_code": "RB-12345678", "legal_address": "Calle 1 #2, Centro, La Habana",
            "company_name": "Resilience Store SA", "tax_certificate": PNG,
            "operating_license": PNG})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"
        doc = _db().kyc_verifications.find_one({"user_id": EMP_ID}, {"_id": 0})
        assert doc["kind"] == "company"
        assert doc["company_fields"]["fiscal_code"] == "RB-12345678"
        assert doc["company_fields"]["legal_address"].startswith("Calle 1")
        assert {d["doc_type"] for d in doc["documents"]} == {"tax_certificate", "operating_license"}

    def test_company_submit_requires_fiscal_and_address(self):
        # Espacios en blanco pasan min_length pero el backend los rechaza.
        r = requests.post(f"{API}/kyc/company/submit", headers=_hdr(EMP_TOKEN), json={
            "fiscal_code": "   ", "legal_address": "      ",
            "tax_certificate": PNG, "operating_license": PNG})
        assert r.status_code == 400, r.text

    def test_non_company_role_forbidden(self):
        r = requests.post(f"{API}/kyc/company/submit", headers=_hdr(NORMAL_TOKEN), json={
            "fiscal_code": "X-1", "legal_address": "addr addr",
            "tax_certificate": PNG, "operating_license": PNG})
        assert r.status_code == 403, r.text

    def test_company_blocked_from_individual_kyc(self):
        r = requests.post(f"{API}/kyc/submit", headers=_hdr(EMP_TOKEN), json={
            "id_front": PNG, "id_back": PNG, "selfie": PNG})
        assert r.status_code == 400, r.text

    def test_admin_approval_sets_kyc_verified(self):
        requests.post(f"{API}/kyc/company/submit", headers=_hdr(EMP_TOKEN), json={
            "fiscal_code": "RB-999", "legal_address": "Dir legal 123",
            "tax_certificate": PNG, "operating_license": PNG})
        doc = _db().kyc_verifications.find_one({"user_id": EMP_ID})
        rid = doc["id"]
        r = requests.post(f"{API}/admin/kyc/{rid}/approve", headers=_hdr(ADMIN_TOKEN),
                          json={"notes": "ok empresa"})
        assert r.status_code == 200, r.text
        user = _db().users.find_one({"user_id": EMP_ID}, {"_id": 0, "kyc_status": 1})
        assert user["kyc_status"] == "verified"
