"""iter91 — Company accounting closing PDF regression tests.

Endpoint: GET /api/admin/company-funds/closing.pdf?since=&until=

Coverage:
- Only actors with the `company_funds` permission can download it.
- Range params are optional; empty → "histórico completo".
- The PDF contains: 'CIERRE EMPRESA' header, an 'Emisor:' line, the
  three summary sections and the shared signature+stamp block.
- Legacy `?date=` shape is NOT supported here (this endpoint is
  distinct from `/api/vip/daily-closing`).
"""
import requests
from pypdf import PdfReader
from io import BytesIO

from conftest import (
    BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL,
)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _pdf_text(content: bytes) -> str:
    r = PdfReader(BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in r.pages)


class TestCompanyClosingPdf:
    URL = f"{BASE_URL}/api/admin/company-funds/closing.pdf"

    def test_admin_can_download(self):
        r = requests.get(
            self.URL,
            params={"since": "2020-01-01", "until": "2099-12-31"},
            headers=_h(ADMIN),
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        # Signature block is expected on the last page.
        txt = _pdf_text(r.content)
        # iter94 — post-personal-name removal, we only assert the short
        # "Firma / Sello" label; the seal + signature IMAGES carry the
        # legal weight.
        assert "Firma / Sello" in txt

    def test_pdf_body_has_expected_sections(self):
        r = requests.get(
            self.URL,
            params={"since": "2020-01-01", "until": "2099-12-31"},
            headers=_h(ADMIN),
        )
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        assert "CIERRE EMPRESA" in txt
        assert "CIERRE CONTABLE EMPRESA" in txt
        assert "TESORERÍA POR MONEDA" in txt
        assert "INGRESOS POR MONEDA" in txt
        # KPI card labels.
        assert "Órdenes ejecutadas" in txt
        assert "Volumen bruto USD" in txt
        assert "Tesorería neta USD" in txt

    def test_empty_range_gets_full_history(self):
        r = requests.get(self.URL, headers=_h(ADMIN))
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        assert "histórico completo" in txt.lower()

    def test_single_date_range_gets_single_day_title(self):
        r = requests.get(
            self.URL,
            params={"since": "2026-01-15", "until": "2026-01-15"},
            headers=_h(ADMIN),
        )
        assert r.status_code == 200
        txt = _pdf_text(r.content)
        # Not "al" — same-day should collapse to just "Reporte del ...".
        assert "Reporte del 2026-01-15" in txt
        assert " al " not in txt.split("Reporte del 2026-01-15")[1][:40]

    def test_vip_client_forbidden(self):
        r = requests.get(self.URL, headers=_h(VIP))
        assert r.status_code == 403

    def test_normal_client_forbidden(self):
        r = requests.get(self.URL, headers=_h(NORMAL))
        assert r.status_code == 403

    def test_invalid_date_returns_400(self):
        r = requests.get(
            self.URL, params={"since": "not-a-date"}, headers=_h(ADMIN),
        )
        assert r.status_code == 400
