"""iter358 — POS Caja: endpoint /admin/pos/cobro (COBRO REAL).

Cobertura:
- registra movimiento 'venta', descuenta stock, respuesta trae movement+ticket.
- open_drawer SIEMPRE True (es un cobro real, no respeta toggle).
- escpos contiene drawer kick (1b 70 00 19 fa) y raster del logo (1d 76 30).
- stock insuficiente → 400, stock no cambia.
- cantidad fraccionaria en producto por unidad → 400.
- sin unit_price → usa price_usd del producto; con unit_price → ese.
- sin auth → 401/403.
"""
import base64
import os
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
AGUA = "cce2f679-3982-4cf0-9972-b25c56f47365"   # unidad, price 240
ARROZ = "5e72a1b1-f95d-415e-900e-062f3c951355"  # unidad, price 800

DRAWER_PULSE_HEX = "1b70001"  # ESC p 0 .. (first bytes of drawer kick)
RASTER_HEADER_HEX = "1d7630"  # GS v 0 (raster bit image)


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _stock(pid):
    r = requests.get(f"{API}/admin/inventory/control", headers=_hdr())
    r.raise_for_status()
    for p in r.json():
        if p["product_id"] == pid:
            return p["stock"]
    raise AssertionError(f"product {pid} not found")


def test_cobro_registra_venta_y_descuenta_stock():
    before = _stock(AGUA)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "product_id": AGUA, "quantity": 1,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "movement" in data
    mov = data["movement"]
    assert mov["type"] == "venta"
    assert mov["product_id"] == AGUA
    assert mov["quantity"] == 1
    assert mov["unit_price"] == 240.0  # default price_usd
    assert mov["total"] == 240.0
    assert mov.get("product_name") == "Agua pequeña"
    # Open drawer SIEMPRE
    assert data["open_drawer"] is True
    assert data["has_logo"] is True
    # ESC/POS debe contener drawer kick + raster del logo
    esc = base64.b64decode(data["escpos_b64"]).hex()
    assert DRAWER_PULSE_HEX in esc, "drawer kick missing"
    assert RASTER_HEADER_HEX in esc, "logo raster missing"
    # Stock descontado
    after = _stock(AGUA)
    assert after == before - 1, f"stock not decremented: {before} -> {after}"


def test_cobro_siempre_abre_gaveta_sin_toggle():
    """El toggle no viaja en el payload de cobro: open_drawer=True siempre."""
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "product_id": AGUA, "quantity": 1,
    })
    assert r.status_code == 200, r.text
    assert r.json()["open_drawer"] is True


def test_cobro_stock_insuficiente_devuelve_400_y_no_descuenta():
    before = _stock(AGUA)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "product_id": AGUA, "quantity": before + 100,
    })
    assert r.status_code == 400, r.text
    detail = (r.json().get("detail") or "").lower()
    assert "stock" in detail and ("insuficiente" in detail or "insuf" in detail)
    assert _stock(AGUA) == before


def test_cobro_cantidad_fraccionaria_en_producto_por_unidad_400():
    before = _stock(ARROZ)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "product_id": ARROZ, "quantity": 1.5,
    })
    assert r.status_code == 400, r.text
    assert _stock(ARROZ) == before


def test_cobro_con_unit_price_explicito_usa_ese():
    before = _stock(AGUA)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "product_id": AGUA, "quantity": 1, "unit_price": 123.45,
    })
    assert r.status_code == 200, r.text
    mov = r.json()["movement"]
    assert mov["unit_price"] == 123.45
    assert abs(mov["total"] - 123.45) < 1e-6
    assert _stock(AGUA) == before - 1


def test_cobro_sin_auth_rechaza():
    r = requests.post(f"{API}/admin/pos/cobro",
                      headers={"Content-Type": "application/json"},
                      json={"product_id": AGUA, "quantity": 1})
    assert r.status_code in (401, 403), r.text
