"""iter111 — VIP Ledger PDF export regression tests.

Endpoints under test:
  GET /api/vip/ledger/export.pdf
  GET /api/admin/vip-ledger/{vip_user_id}/export.pdf

Coverage:
  1. VIP can download own statement (200 + %PDF magic).
  2. Default range applied when both dates omitted (last 90 days label).
  3. Admin can download any VIP's ledger PDF.
  4. Normal user / non-VIP forbidden from own endpoint (403).
  5. Non-VIP target on admin endpoint → 422.
  6. Unknown user_id → 404.
  7. Invalid date parameter → 400.
  8. A confirmed deposit renders as a movement row + updates running balance.
  9. A rejected deposit is EXCLUDED from the statement.
 10. Explicit date range respects filters (movement outside range → not in body).
"""
import os
import requests
from io import BytesIO

from pypdf import PdfReader

from conftest import (
    BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL,
)

VIP_URL = f"{BASE_URL}/api/vip/ledger/export.pdf"
ADMIN_URL_TPL = f"{BASE_URL}/api/admin/vip-ledger/{{uid}}/export.pdf"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _pdf_text(content: bytes) -> str:
    r = PdfReader(BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def _reset_ledger():
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for col in ("vip_capital_deposits", "vip_settlements",
                 "vip_batch_items", "vip_batches", "vip_ledger"):
        db[col].delete_many({"vip_user_id": "user_test_vip01"})
    db.rates.update_one(
        {"from_code": "USDT", "to_code": "USDT"},
        {"$set": {"from_code": "USDT", "to_code": "USDT",
                  "rate_normal": 1.0, "rate_vip": 1.0, "real_rate": 1.0}},
        upsert=True,
    )


def _seed_capital_deposit(amount: float, note: str) -> str:
    """iter166 — POST /vip/capital-deposits is retired (410); seed directly."""
    import uuid as _uuid
    from datetime import datetime, timezone
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    did = f"vdep_test_{_uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    db.vip_capital_deposits.insert_one({
        "id": did, "vip_user_id": "user_test_vip01",
        "vip_email": "vip.test@resilience.com", "vip_name": "VIP Test",
        "currency": "USDT", "amount": float(amount), "deposit_method": "cash",
        "account_holder": None, "tx_hash": None, "proof_url": None,
        "note": note, "status": "pending", "balance_delta_usdt": None,
        "admin_note": None, "reviewed_at": None, "reviewed_by": None,
        "created_at": now, "updated_at": now,
    })
    return did



class TestVipLedgerPdf:
    def test_vip_can_download_default_range(self):
        _reset_ledger()
        r = requests.get(VIP_URL, headers=_h(VIP))
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        txt = _pdf_text(r.content)
        assert "ESTADO DE CUENTA VIP" in txt
        assert "SALDOS DEL PERÍODO" in txt
        assert "DETALLE DE MOVIMIENTOS" in txt
        assert "Firma / Sello" in txt

    def test_normal_user_forbidden(self):
        r = requests.get(VIP_URL, headers=_h(NORMAL))
        assert r.status_code == 403

    def test_admin_can_download_any_vip(self):
        _reset_ledger()
        r = requests.get(
            ADMIN_URL_TPL.format(uid="user_test_vip01"), headers=_h(ADMIN),
        )
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_admin_non_vip_target_rejected(self):
        r = requests.get(
            ADMIN_URL_TPL.format(uid="user_test_normal01"), headers=_h(ADMIN),
        )
        assert r.status_code == 422

    def test_admin_unknown_user_returns_404(self):
        r = requests.get(
            ADMIN_URL_TPL.format(uid="user_does_not_exist"), headers=_h(ADMIN),
        )
        assert r.status_code == 404

    def test_normal_user_forbidden_on_admin_endpoint(self):
        r = requests.get(
            ADMIN_URL_TPL.format(uid="user_test_vip01"), headers=_h(NORMAL),
        )
        assert r.status_code == 403

    def test_invalid_from_date_returns_400(self):
        r = requests.get(VIP_URL, params={"from_date": "not-a-date"}, headers=_h(VIP))
        assert r.status_code == 400

    def test_confirmed_deposit_appears_in_pdf(self):
        _reset_ledger()
        # Seed + confirm a capital deposit so it moves the ledger.
        did = _seed_capital_deposit(7500, "capital regresión")
        r_conf = requests.post(
            f"{BASE_URL}/api/admin/vip-capital-deposits/{did}/confirm",
            headers=_h(ADMIN),
        )
        assert r_conf.status_code == 200

        r = requests.get(VIP_URL, headers=_h(VIP))
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        assert "capital regresión" in txt or "capital regresi" in txt
        # Amount + running balance rendered
        assert "7,500.00" in txt
        # Executive card shows non-zero final balance
        assert "+7,500.00" in txt or "+$7,500.00" in txt
        _reset_ledger()

    def test_rejected_deposit_excluded_from_pdf(self):
        _reset_ledger()
        did = _seed_capital_deposit(3333, "descartado")
        r_rej = requests.post(
            f"{BASE_URL}/api/admin/vip-capital-deposits/{did}/reject",
            headers=_h(ADMIN),
            json={"admin_note": "duplicado"},
        )
        assert r_rej.status_code == 200

        r = requests.get(VIP_URL, headers=_h(VIP))
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        # A rejected deposit must NOT appear in the formal statement.
        assert "descartado" not in txt
        assert "3,333" not in txt
        _reset_ledger()

    def test_explicit_range_filters_out_movements_outside_window(self):
        _reset_ledger()
        # Confirmed deposit lands "today" — request a past range with no
        # activity so the statement carries zero movements.
        did = _seed_capital_deposit(1234, "hoy")
        requests.post(
            f"{BASE_URL}/api/admin/vip-capital-deposits/{did}/confirm",
            headers=_h(ADMIN),
        )
        r = requests.get(
            VIP_URL,
            params={"from_date": "2020-01-01", "to_date": "2020-06-30"},
            headers=_h(VIP),
        )
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        assert "1,234" not in txt
        _reset_ledger()
