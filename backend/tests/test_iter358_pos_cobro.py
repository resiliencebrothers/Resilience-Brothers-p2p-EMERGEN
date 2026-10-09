"""iter358/iter359 — POS Caja: endpoint /admin/pos/cobro (COBRO REAL multi-línea).

Cobertura:
- una línea: registra 'venta', descuenta stock, respuesta trae movements+ticket.
- multi-línea: total combinado, pagado y cambio correctos; stock por línea.
- open_drawer SIEMPRE True (es un cobro real, no respeta toggle).
- escpos contiene drawer kick (1b 70 00 19 fa) y raster del logo (1d 76 30).
- efectivo OBLIGATORIO: si es menor que el total → 400 y no descuenta.
- stock insuficiente → 400, stock no cambia.
- PRE-VALIDA todo el carrito: si una línea falla, NO cobra ninguna (sin parcial).
- cantidad fraccionaria en producto por unidad → 400.
- sin auth → 401/403.
"""
import base64
import requests

from tests.conftest import BASE_URL, ADMIN_TOKEN

API = f"{BASE_URL}/api"
AGUA = "cce2f679-3982-4cf0-9972-b25c56f47365"   # unidad, price 240
ARROZ = "5e72a1b1-f95d-415e-900e-062f3c951355"  # unidad, price 800

DRAWER_PULSE_HEX = "1b700019fa"  # ESC p 0 25 250 (cash drawer kick)
RASTER_HEADER_HEX = "1d7630"     # GS v 0 (raster bit image del logo)


def _hdr(tok=ADMIN_TOKEN):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _stock(pid):
    r = requests.get(f"{API}/admin/inventory/control", headers=_hdr())
    r.raise_for_status()
    for p in r.json():
        if p["product_id"] == pid:
            return p["stock"]
    raise AssertionError(f"product {pid} not found")


def test_cobro_una_linea_registra_descuenta_y_calcula_cambio():
    before = _stock(AGUA)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "items": [{"product_id": AGUA, "quantity": 1}], "paid": 500,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    movs = data["movements"]
    assert len(movs) == 1
    assert movs[0]["type"] == "venta" and movs[0]["product_id"] == AGUA
    assert movs[0]["unit_price"] == 240.0 and movs[0]["total"] == 240.0
    assert data["total"] == 240.0 and data["paid"] == 500.0 and data["change"] == 260.0
    assert data["open_drawer"] is True and data["has_logo"] is True
    esc = base64.b64decode(data["escpos_b64"]).hex()
    assert DRAWER_PULSE_HEX in esc and RASTER_HEADER_HEX in esc
    # El ticket muestra pagado y cambio.
    assert "Pagado" in data["plaintext"] and "Cambio" in data["plaintext"]
    assert _stock(AGUA) == before - 1


def test_cobro_multilinea_total_combinado_y_stock_por_linea():
    a0, r0 = _stock(AGUA), _stock(ARROZ)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "items": [{"product_id": AGUA, "quantity": 1},
                  {"product_id": ARROZ, "quantity": 2}], "paid": 2000,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["movements"]) == 2
    assert data["total"] == 1840.0          # 240 + 2*800
    assert data["change"] == 160.0          # 2000 - 1840
    assert data["open_drawer"] is True
    assert _stock(AGUA) == a0 - 1 and _stock(ARROZ) == r0 - 2


def test_cobro_efectivo_insuficiente_400_y_no_descuenta():
    before = _stock(AGUA)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "items": [{"product_id": AGUA, "quantity": 1}], "paid": 100,
    })
    assert r.status_code == 400, r.text
    assert "insuficiente" in (r.json().get("detail") or "").lower()
    assert _stock(AGUA) == before


def test_cobro_stock_insuficiente_400_y_no_descuenta():
    before = _stock(AGUA)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "items": [{"product_id": AGUA, "quantity": before + 100}], "paid": 99_999_999,
    })
    assert r.status_code == 400, r.text
    assert "stock" in (r.json().get("detail") or "").lower()
    assert _stock(AGUA) == before


def test_cobro_prevalida_carrito_no_cobra_parcial():
    """Si una línea falla (stock), NINGUNA línea se cobra (pre-validación)."""
    a0, r0 = _stock(AGUA), _stock(ARROZ)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "items": [{"product_id": AGUA, "quantity": 1},
                  {"product_id": ARROZ, "quantity": r0 + 500}], "paid": 99_999_999,
    })
    assert r.status_code == 400, r.text
    # AGUA (línea válida) NO debe haberse descontado: no hay cobro parcial.
    assert _stock(AGUA) == a0 and _stock(ARROZ) == r0


def test_cobro_fraccion_en_producto_por_unidad_400():
    before = _stock(ARROZ)
    r = requests.post(f"{API}/admin/pos/cobro", headers=_hdr(), json={
        "items": [{"product_id": ARROZ, "quantity": 1.5}], "paid": 99_999,
    })
    assert r.status_code == 400, r.text
    assert _stock(ARROZ) == before


def test_cobro_sin_auth_rechaza():
    r = requests.post(f"{API}/admin/pos/cobro",
                      headers={"Content-Type": "application/json"},
                      json={"items": [{"product_id": AGUA, "quantity": 1}], "paid": 500})
    assert r.status_code in (401, 403), r.text
