"""iter309 — Extractos PDF reales tipo Sabadell (texto digital vertical).

Un extracto Sabadell («Consulta de movimientos») exportado a PDF trae miles
de filas en layout VERTICAL: cada campo en su propia línea (fecha, concepto,
importe). La ruta anterior mandaba TODO el texto a la IA pidiendo un único
array JSON; con 2000+ filas la respuesta se truncaba y el import 'FALLÓ' con
0 detectados («LLM response has no JSON array»).

Corrección: `parse_pdf_text_native` lee las filas de forma DETERMINISTA (sin
IA) cuando detecta la firma de cabecera ES vertical. La IA queda de respaldo
para otros formatos. Además el remitente ahora sale también de
'TRANSFERENCIA <NOMBRE>' sin 'DE'.
"""
import asyncio
import io

from services.reconciliation_parser import (
    parse_pdf_text_native, parse_statement, sender_from_description,
    _es_vertical_header_index,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


_VERTICAL_TEXT = "\n".join([
    "Consulta de movimientos",
    "13/09/2026 17:14:30",
    "Cuenta:", "0081-5234-14-0001728673",
    "Divisa:", "EUR",
    "Titular:", "BASA TRAVEL AGENCY SL.",
    "Selección:", "Desde 01/09/2026 hasta 14/09/2026.",
    "F. Operativa", "Concepto", "Importe",
    "14/09/2026", "ABONO TRANSFERENCIA DE JUAN PEREZ GOMEZ", "110.00",
    "14/09/2026", "TRANSFERENCIA LIZANDRA GE DIAZ", "55.00",
    "13/09/2026", "INGRESO EFECTIVO CAJERO AUTOMATICO 008157350050/BASA", "50.00",
    "12/09/2026", "ABONO TRANSFERENCIA DE Trustly Group AB", "1.234,56",
    "11/09/2026", "COMISIONES", "-18",
])


class TestNativeVerticalParsing:
    def test_parses_all_rows_without_llm(self):
        txs = parse_pdf_text_native(_VERTICAL_TEXT, dayfirst=True)
        assert len(txs) == 5, txs
        credits = [t for t in txs if t["direction"] == "credit"]
        debits = [t for t in txs if t["direction"] == "debit"]
        assert len(credits) == 4 and len(debits) == 1
        assert txs[0]["transaction_date"] == "2026-09-14"
        assert txs[0]["amount"] == 110.0
        # importe EU '1.234,56' → 1234.56
        assert txs[3]["amount"] == 1234.56
        # débito 'COMISIONES' → importe absoluto 18, dirección debit
        assert debits[0]["amount"] == 18.0
        assert debits[0]["description"] == "COMISIONES"

    def test_sender_extracted_including_transferencia_without_de(self):
        txs = parse_pdf_text_native(_VERTICAL_TEXT, dayfirst=True)
        assert txs[0]["sender_name"] == "JUAN PEREZ GOMEZ"
        # 'TRANSFERENCIA <NOMBRE>' sin 'DE'
        assert txs[1]["sender_name"] == "LIZANDRA GE DIAZ"
        # 'INGRESO EFECTIVO CAJERO...' no tiene remitente → None
        assert txs[2]["sender_name"] is None

    def test_header_signature_detected(self):
        lines = [ln.strip() for ln in _VERTICAL_TEXT.splitlines() if ln.strip()]
        idx = _es_vertical_header_index(lines)
        assert idx is not None and lines[idx].lower().startswith("f. operativa")

    def test_gate_returns_empty_for_non_es_pdf(self):
        """Un PDF sin la firma de cabecera ES vertical NO se toca (la IA sigue
        de respaldo) — evita secuestrar extractos de otros bancos."""
        other = "\n".join([
            "MONTHLY STATEMENT", "Wells Fargo", "Account 1234",
            "Some narrative paragraph without a vertical table layout.",
            "Thank you for banking with us.",
        ])
        assert parse_pdf_text_native(other, dayfirst=False) == []
        lines = [ln.strip() for ln in other.splitlines() if ln.strip()]
        assert _es_vertical_header_index(lines) is None


class TestSenderPattern:
    def test_transferencia_without_de(self):
        assert sender_from_description(
            "TRANSFERENCIA LIZANDRA GE DIAZ") == "LIZANDRA GE DIAZ"

    def test_transferencia_de_still_works(self):
        assert sender_from_description(
            "ABONO TRANSFERENCIA DE JUAN PEREZ GOMEZ") == "JUAN PEREZ GOMEZ"
        assert sender_from_description(
            "TRANSFERENCIA INMEDIATA DE MARIA LOPEZ") == "MARIA LOPEZ"

    def test_no_sender_for_cash_and_fees(self):
        assert sender_from_description("COMISIONES") is None
        assert sender_from_description(
            "INGRESO EFECTIVO CAJERO AUTOMATICO 0081") is None


class TestEndToEndPdf:
    def _build_pdf(self, text: str) -> bytes:
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        y = 800
        for ln in text.splitlines():
            c.drawString(40, y, ln)
            y -= 16
            if y < 40:
                c.showPage()
                y = 800
        c.save()
        return buf.getvalue()

    def test_pdf_parses_natively_end_to_end(self):
        """parse_statement sobre un PDF de texto digital vertical debe usar el
        parser NATIVO (mode='pdf_text_native'), NUNCA la IA."""
        data = self._build_pdf(_VERTICAL_TEXT)
        txs, errors, mode = _run(parse_statement(data, "pdf", dayfirst=True))
        assert mode == "pdf_text_native", f"debe ser nativo, sin IA: {mode}"
        assert errors == 0
        assert len(txs) == 5
        assert sum(1 for t in txs if t["direction"] == "credit") == 4
