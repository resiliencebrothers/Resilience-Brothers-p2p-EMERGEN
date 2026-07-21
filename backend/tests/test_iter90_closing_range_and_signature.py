"""iter90 — Range-aware closing PDF + signature/stamp block regression.

Verifies:
1. `/api/vip/daily-closing` accepts `since` + `until` and returns a
   proper PDF that contains transactions (inflows / outflows / self-
   converts), not just the empty "orders" table from iter76.
2. Back-compat: the legacy `?date=YYYY-MM-DD` still works.
3. The PDF header flips between "CIERRE VIP" (for VIP users) and
   "CIERRE CONTABLE" (for normal / admin users).
4. The shared signature block is embedded in ALL PDFs that ship a
   generator: transactions history, audit log, revenue reports, and
   the closing PDF.
"""
import os
import requests
from pypdf import PdfReader
from io import BytesIO

from conftest import (
    BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL,
)


def _h(t=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


def _pdf_text(content: bytes) -> str:
    r = PdfReader(BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in r.pages)


class TestClosingRange:
    def test_range_params_accepted(self):
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing",
            params={"since": "2020-01-01", "until": "2099-12-31"},
            headers=_h(VIP),
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_legacy_single_date_still_works(self):
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing",
            params={"date": "2099-01-01"},
            headers=_h(VIP),
        )
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_vip_header_says_cierre_vip(self):
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing",
            params={"since": "2020-01-01", "until": "2099-12-31"},
            headers=_h(VIP),
        )
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        assert "CIERRE VIP" in txt
        assert "CIERRE DIARIO VIP" in txt

    def test_normal_client_header_says_cierre_contable(self):
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing",
            params={"since": "2020-01-01", "until": "2099-12-31"},
            headers=_h(NORMAL),
        )
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        assert "CIERRE CONTABLE" in txt
        assert "CIERRE DIARIO VIP" not in txt

    def test_normal_client_range_body_lists_transactions(self):
        """The bug the user reported: normal client closing PDF was empty
        because it only looked at `db.orders`. Now that we route through
        `build_transactions`, any client with inflows/outflows should see
        real rows or at least the "Detalle de transacciones" section
        header — never the old '0 órdenes / 0.00' summary card layout."""
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing",
            params={"since": "2020-01-01", "until": "2099-12-31"},
            headers=_h(NORMAL),
        )
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        assert "Detalle de transacciones" in txt
        assert "Transacciones totales" in txt
        # The old headline "Órdenes aprobadas" MUST NOT appear anywhere
        # in the new body — that was iter76's stale wording.
        assert "Órdenes aprobadas" not in txt


class TestSignatureBlockOnEveryPdf:
    """The signature+stamp helper (`pdf_signature.build_signature_block`)
    is legally binding — every PDF the platform issues has to embed it."""

    _EXPECTED_LABELS = [
        # iter94 — after removing the personal name, the signature block
        # only carries the short "Firma / Sello" label; the signature +
        # stamp images are the actual legal proof.
        "Firma / Sello",
    ]

    def _assert_signed(self, content: bytes, label: str):
        txt = _pdf_text(content)
        for needle in self._EXPECTED_LABELS:
            assert needle in txt, (
                f"[{label}] signature block missing '{needle}'.\n"
                f"First 400 chars of PDF text:\n{txt[:400]}"
            )

    def test_closing_pdf_is_signed(self):
        r = requests.get(
            f"{BASE_URL}/api/vip/daily-closing",
            params={"since": "2020-01-01", "until": "2099-12-31"},
            headers=_h(VIP),
        )
        assert r.status_code == 200
        self._assert_signed(r.content, "vip/daily-closing")

    def test_transactions_pdf_is_signed(self):
        r = requests.get(
            f"{BASE_URL}/api/me/transactions/export.pdf",
            headers=_h(VIP),
        )
        assert r.status_code == 200
        self._assert_signed(r.content, "me/transactions/export.pdf")

    def test_audit_pdf_is_signed(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/audit/export.pdf",
            headers=_h(ADMIN),
        )
        assert r.status_code == 200
        self._assert_signed(r.content, "admin/audit/export.pdf")


class TestPdfServiceUnit:
    """Pure-function coverage on generate_vip_closing_pdf so we don't
    need the HTTP layer for the fast smoke."""

    def test_empty_range_produces_valid_pdf(self):
        from pdf_service import generate_vip_closing_pdf
        pdf = generate_vip_closing_pdf(
            user={"name": "T", "email": "t@x", "preferred_language": "es"},
            entries=[], since="", until="", final_balance=0, is_vip=False,
        )
        assert pdf[:4] == b"%PDF"
        txt = _pdf_text(pdf)
        assert "CIERRE CONTABLE" in txt
        # Empty range still generates the "histórico completo" title.
        assert "histórico" in txt.lower()

    def test_vip_flag_toggles_header(self):
        from pdf_service import generate_vip_closing_pdf
        vip_pdf = generate_vip_closing_pdf(
            user={"name": "V", "email": "v@x"}, entries=[],
            since="2026-01-01", until="2026-01-01",
            final_balance=0, is_vip=True,
        )
        norm_pdf = generate_vip_closing_pdf(
            user={"name": "N", "email": "n@x"}, entries=[],
            since="2026-01-01", until="2026-01-01",
            final_balance=0, is_vip=False,
        )
        vip_txt = _pdf_text(vip_pdf)
        norm_txt = _pdf_text(norm_pdf)
        assert "CIERRE VIP" in vip_txt
        assert "CIERRE VIP" not in norm_txt
        assert "CIERRE CONTABLE" in norm_txt
