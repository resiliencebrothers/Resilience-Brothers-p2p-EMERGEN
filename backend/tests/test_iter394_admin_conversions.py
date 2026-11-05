"""iter394 — Correcciones de la revisión Resilience_Clasificacion.

Pendiente #1 (RESUELTO): las conversiones internas (`vip.convert`) ahora se
incorporan al registro ADMIN general (sin user_id), no solo al personal.

Verifica, contra la API real:
  - El registro admin incluye filas direction=="conversion" con cliente,
    monedas, importe y referencia.
  - El filtro de origen `ref_type=conversion` las aísla.
  - El filtro por `holder` (cliente) las acota.
  - Los totales cuentan las conversiones aparte y NUNCA las suman a in/out
    (no hay segundo crédito).
  - El registro PERSONAL sigue acotado por usuario (admin ve >= que un cliente).
  - Deny-by-default: anónimo 401.

También cubre el resolutor `_resolve_sale_origin` (groundwork "tienda en venta").
"""
import os

import requests

from tests.conftest import ADMIN_TOKEN, NORMAL_TOKEN, BASE_URL

API = f"{BASE_URL}/api"


def _admin(params=None):
    return requests.get(
        f"{API}/admin/transactions",
        params=params or {},
        cookies={"session_token": ADMIN_TOKEN},
        timeout=30,
    )


class TestAdminConversions:
    def test_anonymous_denied(self):
        r = requests.get(f"{API}/admin/transactions", params={"ref_type": "conversion"}, timeout=30)
        assert r.status_code == 401

    def test_admin_register_includes_conversions(self):
        r = _admin({"ref_type": "conversion", "limit": 50})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) > 0, "el registro admin debe incluir conversiones"
        for it in items:
            assert it["direction"] == "conversion"
            assert it["ref_type"] == "conversion"
            assert it.get("from_code") and it.get("to_code")
            assert "client_name" in it
            assert it.get("ref_id")

    def test_totals_count_conversions_without_touching_in_out(self):
        r = _admin({"ref_type": "conversion", "limit": 500})
        assert r.status_code == 200
        totals = r.json()["totals"]
        assert totals.get("conversion_count", 0) > 0
        # Una conversión no es ni entrada ni salida: no puede contaminar in/out.
        for slot in totals.get("by_currency", {}).values():
            assert "conversion" not in slot
            assert set(slot.keys()) <= {"in", "out", "count"}

    def test_holder_filter_narrows_conversions(self):
        full = _admin({"ref_type": "conversion", "limit": 500})
        assert full.status_code == 200
        items = full.json()["items"]
        assert items
        name = (items[0].get("client_name") or "").strip()
        if not name:
            return
        token = name.split()[0]
        narrowed = _admin({"ref_type": "conversion", "holder": token, "limit": 500})
        assert narrowed.status_code == 200
        narrowed_items = narrowed.json()["items"]
        assert len(narrowed_items) >= 1
        assert len(narrowed_items) <= len(items)
        for it in narrowed_items:
            hay = f"{it.get('client_name','')} {it.get('holder_name','')}".lower()
            assert token.lower() in hay

    def test_admin_sees_more_than_single_user(self):
        """Confirma el fix: antes el admin NO veía conversiones; ahora el
        registro admin (todos los clientes) es >= el personal de un cliente."""
        admin_c = _admin({"ref_type": "conversion", "limit": 500}).json()["items"]
        personal = requests.get(
            f"{API}/me/transactions",
            params={"direction": "conversion"},
            cookies={"session_token": NORMAL_TOKEN},
            timeout=30,
        )
        assert personal.status_code == 200
        personal_c = [i for i in personal.json()["items"] if i["direction"] == "conversion"]
        # El admin agrega las de TODOS los clientes → nunca menos que un cliente.
        assert len(admin_c) >= len(personal_c)

    def test_in_out_filters_exclude_conversions(self):
        for d in ("in", "out"):
            r = _admin({"direction": d, "limit": 200})
            assert r.status_code == 200
            assert all(it["direction"] != "conversion" for it in r.json()["items"])


class TestSaleOriginResolver:
    """Groundwork 'tienda en venta': cada venta captura su origen honesto."""

    def test_resolver_branches(self):
        from routes.orders import _resolve_sale_origin as f
        # Empresa, entrega a domicilio → almacén central de esa empresa.
        k, i, n = f({"company_id": "cmp1", "owner_id": "cmp1", "owner_name": "Mi Empresa"}, None, "delivery")
        assert (k, i) == ("central", "cmp1") and "Almacén central" in n
        # Recogida en sucursal → la tienda física elegida.
        k, i, n = f({"company_id": "cmp1", "owner_name": "Mi Empresa"},
                    {"id": "st1", "name": "Sucursal Centro"}, "store_pickup")
        assert (k, i, n) == ("branch", "st1", "Sucursal Centro")
        # Producto de vendedor VIP (owner_id sin company_id).
        k, i, n = f({"owner_id": "vip9", "owner_name": "Vendedor Juan"}, None, "delivery")
        assert (k, i, n) == ("vendor", "vip9", "Vendedor Juan")
        # Inventario propio de la plataforma.
        k, i, n = f({}, None, "delivery")
        assert (k, i, n) == ("platform", "", "Almacén propio")
        # Pickup declarado pero sin tienda cargada → no inventa sucursal.
        k, i, _ = f({"company_id": "cmp1", "owner_name": "X"}, None, "store_pickup")
        assert k == "central" and i == "cmp1"


def test_env_present():
    assert os.environ.get("REACT_APP_BACKEND_URL")
