"""iter308 — Regla de nombres aprobada por el propietario (CB08 reformulado,
doc Instrucciones_Emergent_Conciliacion_Regla_y_CB03).

Regla: para validar la correspondencia entre una operación y una transferencia
basta el IMPORTE EXACTO + al menos UN nombre + UN apellido (cualquiera de los
nombres/apellidos), con normalización de mayúsculas, acentos, puntuación y
orden. No se exige el nombre completo ni separar nombres de apellidos. Una
palabra que también puede ser nombre de pila (LEÓN, CRUZ, MIRANDA, VEGA) NO se
convierte en un bloqueo general cuando la estructura la sitúa como apellido.

Estas pruebas codifican los 9 ejemplos del documento como criterio de
aceptación, más los casos "no bloquear" de apellidos de doble función.
"""
from services.reconciliation_matcher import (
    DEFAULT_CONFIG, rank_candidates, decide, surname_similarity,
    name_similarity, normalize_name)

DAY = "2026-03-10"


def _order(name, amount=100.0, oid="ord_x", created=DAY, **extra):
    doc = {"id": oid, "status": "pending", "kind": "order",
           "from_code": "EUR", "currency": "EUR", "amount_from": float(amount),
           "user_name": name, "sender_name": name, "created_at": created}
    doc.update(extra)
    return doc


def _tx(sender, amount=100.0, currency="EUR", date=DAY):
    return {"id": "tx_x", "status": "manual_review", "direction": "credit",
            "amount": float(amount), "currency": currency,
            "sender_name": sender, "transaction_date": date}


def _decision(order_name, sender, amount_order=100.0, amount_tx=100.0,
              extra_orders=None):
    orders = [_order(order_name, amount_order, oid="ord_1")]
    if extra_orders:
        for i, (nm, amt) in enumerate(extra_orders, start=2):
            orders.append(_order(nm, amt, oid=f"ord_{i}"))
    tx = _tx(sender, amount_tx)
    ranked = rank_candidates(tx, orders, DEFAULT_CONFIG, "", set())
    return decide(tx, ranked, DEFAULT_CONFIG, "", pool_complete=True)


# ---------------------------------------------------------------------------
# Los 9 ejemplos del documento.
# ---------------------------------------------------------------------------
class TestNameRuleExamples:
    def test_ex1_one_name_one_surname_autovalidates(self):
        d = _decision("José Manuel Pérez García", "José Pérez")
        assert d["decision"] == "auto", d

    def test_ex2_second_name_and_second_surname_serve(self):
        d = _decision("José Manuel Pérez García", "Manuel García")
        assert d["decision"] == "auto", d

    def test_ex3_normalizes_order_accents_and_punctuation(self):
        d = _decision("José Manuel Pérez García", "PEREZ, JOSE")
        assert d["decision"] == "auto", d

    def test_ex4_missing_middle_name_still_autovalidates(self):
        d = _decision("José Manuel Pérez García", "José Pérez García")
        assert d["decision"] == "auto", d

    def test_ex5_two_given_names_no_surname_is_not_auto(self):
        d = _decision("José Manuel Pérez García", "José Manuel")
        assert d["decision"] != "auto", d

    def test_ex6_amount_mismatch_never_auto(self):
        d = _decision("José Manuel Pérez García", "José Pérez",
                      amount_tx=99.0)
        assert d["decision"] != "auto", d

    def test_ex7_currency_mismatch_blocked_at_confirm(self):
        # La moneda se filtra antes de puntuar (órdenes se cargan por moneda) y
        # el confirm valida moneda: un abono USD nunca respalda una orden EUR.
        import asyncio
        from routes.reconciliation import _validate_confirm_compatibility
        from fastapi import HTTPException
        tx = _tx("José Pérez", amount=100.0, currency="USD")
        order = _order("José Manuel Pérez García")

        async def run():
            try:
                await _validate_confirm_compatibility(tx, order)
                return "ok"
            except HTTPException as ex:
                return ex.status_code
        assert asyncio.get_event_loop().run_until_complete(run()) == 409

    def test_ex8_dual_function_surname_as_last_token_autovalidates(self):
        # 'León' es apellido (último token): no debe bloquearse por poder ser
        # también nombre de pila.
        d = _decision("Pedro León", "Pedro León")
        assert d["decision"] == "auto", d

    def test_ex9_two_compatible_orders_go_to_review(self):
        d = _decision("José Manuel Pérez García", "José Pérez García",
                      extra_orders=[("José Manuel Pérez García", 100.0)])
        assert d["decision"] == "review", d


# ---------------------------------------------------------------------------
# Apellidos de doble función NO son bloqueos generales cuando son el apellido.
# ---------------------------------------------------------------------------
class TestDualFunctionSurnamesNotBlocked:
    def test_dual_function_surnames_autovalidate_as_last_token(self):
        for surname in ("León", "Cruz", "Miranda", "Vega"):
            d = _decision(f"Pedro {surname}", f"Pedro {surname}")
            assert d["decision"] == "auto", (surname, d)

    def test_reordered_two_given_names_do_not_prove_surname(self):
        # Control conservado: dos nombres de pila reordenados NO prueban
        # apellido (la regla no se reduce a "dos palabras + importe").
        assert surname_similarity("MANUEL JOSE", "JOSE MANUEL PEREZ") < 0.75
        assert surname_similarity("JOSE MANUEL", "MARIA JOSE") == 0.0

    def test_partial_match_normalization_is_order_independent(self):
        assert name_similarity("PEREZ JOSE", "José Pérez") >= 0.95
        assert normalize_name("PÉREZ, José") == "PEREZ JOSE"


class TestCICoverage:
    def test_makefile_critical_includes_iter308(self):
        from pathlib import Path
        makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        target = makefile.split("test-critical:")[1].split("test-all:")[0]
        assert "test_iter308_regla_nombres_cb08.py" in target
