"""iter204 — geocodificación de direcciones cubanas (fallback progresivo).

Unit tests del parser de variantes (sin red) + contrato del endpoint
/vip/geo-search con provincia (con red, Nominatim público).
"""
import requests

from services.geo_routing import _query_variants
from tests.conftest import BASE_URL, VIP_TOKEN

API = f"{BASE_URL}/api"


class TestQueryVariants:
    def test_entre_clause_is_stripped_and_province_added(self):
        v = _query_variants("SITIOS 204 Entre Lealtad y Campanario", "La Habana")
        assert v[0] == "SITIOS 204 Entre Lealtad y Campanario"
        assert "SITIOS 204, La Habana" in v
        assert "SITIOS, La Habana" in v

    def test_e_slash_abbreviation_keeps_neighborhood(self):
        v = _query_variants("Calle 23 #456 e/ 10 y 12, Vedado", "La Habana")
        assert "Calle 23 #456, Vedado, La Habana" in v

    def test_percent_abbreviation(self):
        v = _query_variants("Monte 561 % Carmen y Figuras, Centro Habana", "La Habana")
        assert "Monte 561, Centro Habana, La Habana" in v

    def test_esquina_clause(self):
        v = _query_variants("Ave 31 esquina a 42, Playa", "La Habana")
        assert "Ave 31, Playa, La Habana" in v

    def test_simple_address_has_single_variant(self):
        assert _query_variants("Hotel habana libre", "") == ["Hotel habana libre"]

    def test_max_four_variants_no_duplicates(self):
        v = _query_variants("SITIOS 204 Entre Lealtad y Campanario", "La Habana")
        assert len(v) <= 4
        assert len({x.lower() for x in v}) == len(v)


class TestGeoReverse:
    def test_reverse_returns_readable_address(self):
        r = requests.get(
            f"{API}/vip/geo-reverse",
            params={"lat": 23.1395146, "lon": -82.3825415},
            headers={"Authorization": f"Bearer {VIP_TOKEN}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "Habana" in data["display_name"]

    def test_reverse_rejects_invalid_coords(self):
        r = requests.get(
            f"{API}/vip/geo-reverse",
            params={"lat": 999, "lon": 0},
            headers={"Authorization": f"Bearer {VIP_TOKEN}"},
            timeout=15,
        )
        assert r.status_code == 400


class TestGeoSearchEndpoint:
    def test_cuban_address_falls_back_and_flags_approximate(self):
        r = requests.get(
            f"{API}/vip/geo-search",
            params={"q": "SITIOS 204 Entre Lealtad y Campanario",
                    "province": "La Habana"},
            headers={"Authorization": f"Bearer {VIP_TOKEN}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["results"]) >= 1
        assert data["approximate"] is True
        assert "SITIOS" in (data.get("matched_query") or "")

    def test_exact_address_is_not_approximate(self):
        r = requests.get(
            f"{API}/vip/geo-search",
            params={"q": "Hotel habana libre"},
            headers={"Authorization": f"Bearer {VIP_TOKEN}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["results"]) >= 1
        assert data["approximate"] is False
