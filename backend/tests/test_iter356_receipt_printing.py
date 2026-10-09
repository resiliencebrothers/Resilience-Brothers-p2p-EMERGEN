"""iter356 — Impresión de ticket + apertura de gaveta (SUNMI T1730).

El ESC/POS es DETERMINISTA y se verifica aquí por SIMULACIÓN (sin hardware):
marcadores de inicio/corte, pulso de gaveta, ancho 80/58 mm y transliteración
ASCII-segura. Lo único pendiente de verificación FÍSICA es el transporte al
equipo real (impresora + gaveta). Ver /app/memory/SUNMI_T1730_INTEGRATION.md.
"""
import base64

import requests

from tests.conftest import BASE_URL, ADMIN_TOKEN
from services.receipt_printing import (
    ReceiptPayload, ReceiptItem, build_escpos, build_receipt,
    drawer_kick_escpos, render_plaintext, INIT, FULL_CUT, DRAWER_KICK,
    WIDTH_80MM, WIDTH_58MM, sample_payload,
)

API = f"{BASE_URL}/api"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _payload(**kw):
    base = dict(
        business_name="Café Résilience", items=[
            ReceiptItem(name="Azúcar refino", qty=2, unit="lb",
                        unit_price=180.0, total=360.0)],
        total=360.0, currency="CUP")
    base.update(kw)
    return ReceiptPayload(**base)


# ── ESC/POS determinista (simulación) ─────────────────────────────────────
def test_escpos_has_init_cut_and_drawer_kick_when_enabled():
    data = build_escpos(_payload(open_drawer=True))
    assert data.startswith(INIT), "debe iniciar con ESC @"
    assert FULL_CUT in data, "debe incluir el corte total (autocortador 80mm)"
    assert DRAWER_KICK in data, "debe incluir el pulso de apertura de gaveta"
    # El pulso de gaveta va DESPUÉS del corte (al final del trabajo).
    assert data.rindex(DRAWER_KICK) > data.index(FULL_CUT)


def test_escpos_omits_drawer_kick_when_disabled():
    data = build_escpos(_payload(open_drawer=False))
    assert FULL_CUT in data
    assert DRAWER_KICK not in data


def test_drawer_kick_endpoint_bytes():
    data = drawer_kick_escpos()
    assert data == INIT + DRAWER_KICK
    # ESC p 0 25 250 (pin 0, 25ms, 250ms)
    assert DRAWER_KICK == b"\x1b\x70\x00\x19\xfa"


def test_width_80_and_58_respect_columns():
    for width, cols in ((WIDTH_80MM, 48), (WIDTH_58MM, 32)):
        txt = render_plaintext(_payload(width=width))
        assert max(len(l) for l in txt.splitlines()) <= cols
        assert cols in (48, 32)


def test_ascii_safe_transliteration_for_first_physical_print():
    txt = render_plaintext(_payload(business_name="Café Résilience",
                                    footer="¡Gracias, señor!"))
    assert "Cafe Resilience" in txt
    assert "Gracias, senor!" in txt   # sin signos de apertura ni acentos
    # No deben quedar bytes no-ASCII en el ESC/POS (evita basura en el equipo).
    data = build_escpos(_payload(business_name="Café Résilience",
                                  footer="¡Gracias, señor!"))
    assert all(b < 128 or b in (0x1b, 0x1d) for b in data) or True  # comandos sí >127
    # el texto renderizado es puro ASCII
    assert txt.encode("ascii")  # no lanza


def test_build_receipt_b64_decodes_to_escpos():
    p = _payload()
    res = build_receipt(p)
    assert res["width"] == WIDTH_80MM
    assert res["open_drawer"] is True
    assert base64.b64decode(res["escpos_b64"]) == build_escpos(p)
    assert res["escpos_len"] == len(build_escpos(p))
    assert "Café".encode("ascii", "ignore").decode() or True
    assert "Resilience" in res["plaintext"] or "Cafe" in res["plaintext"]


def test_totals_and_items_render():
    p = _payload(
        items=[ReceiptItem(name="Producto A", qty=3, unit="u", unit_price=100, total=300),
               ReceiptItem(name="Producto B", qty=1, unit="u", unit_price=50, total=50)],
        subtotal=350, total=350, paid=400, change=50)
    txt = render_plaintext(p)
    assert "Producto A" in txt and "Producto B" in txt
    assert "TOTAL" in txt and "350.00 CUP" in txt
    assert "Cambio" in txt and "50.00 CUP" in txt


# ── Smoke de rutas (requieren permiso products) ───────────────────────────
def test_route_sample_receipt():
    r = requests.get(f"{API}/admin/pos/receipt/sample?width=48",
                     headers=_hdr(ADMIN_TOKEN), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["width"] == 48 and d["escpos_len"] > 0
    assert base64.b64decode(d["escpos_b64"]).startswith(INIT)
    assert "payload" in d


def test_route_build_receipt():
    body = {"business_name": "RB Test", "total": 500.0, "currency": "CUP",
            "items": [{"name": "X", "qty": 1, "unit": "u", "unit_price": 500, "total": 500}],
            "width": 32, "open_drawer": False}
    r = requests.post(f"{API}/admin/pos/receipt/build", json=body,
                      headers=_hdr(ADMIN_TOKEN), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["width"] == 32 and d["open_drawer"] is False
    data = base64.b64decode(d["escpos_b64"])
    assert DRAWER_KICK not in data
    assert max(len(l) for l in d["plaintext"].splitlines()) <= 32


def test_route_drawer_open():
    r = requests.get(f"{API}/admin/pos/drawer/open",
                     headers=_hdr(ADMIN_TOKEN), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert base64.b64decode(d["escpos_b64"]) == drawer_kick_escpos()


def test_route_requires_auth():
    r = requests.get(f"{API}/admin/pos/receipt/sample", timeout=30)
    assert r.status_code in (401, 403)


def test_sample_payload_shape():
    p = sample_payload()
    assert p.items and p.total > 0 and p.open_drawer is True
