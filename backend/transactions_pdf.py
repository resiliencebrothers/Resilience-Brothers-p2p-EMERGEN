"""PDF generation for Transactions Registry export (entradas + salidas).

iter68 — PDF titles, labels and headers are localized based on the caller's
`lang` argument. This is critical for English-speaking users who download
their transactions register from `/dashboard/transactions`.
"""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


BRAND_PURPLE = colors.HexColor("#8B5CF6")
BG_DARK = colors.HexColor("#14101F")
PANEL = colors.HexColor("#1A1730")
BORDER = colors.HexColor("#2a2a2a")
TEXT_MUTED = colors.HexColor("#A3A3A3")
TEXT = colors.HexColor("#FFFFFF")
GREEN = colors.HexColor("#22C55E")
RED = colors.HexColor("#EF4444")

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def _is_en(lang: str) -> bool:
    return (lang or "").lower().startswith("en")


def _t(key: str, lang: str) -> str:
    """Tiny lookup — reportlab-friendly, no external i18n stack."""
    is_en = _is_en(lang)
    _STR = {
        "subtitle": ("Registro de Transacciones — Contabilidad",
                     "Transactions Registry — Accounting"),
        "header_tag": ("TRANSACCIONES", "TRANSACTIONS"),
        "header_sub": ("ENTRADAS · SALIDAS", "INFLOWS · OUTFLOWS"),
        "generated": ("Generado:", "Generated:"),
        "page": ("Página", "Page"),
        "eyebrow": ("/ REGISTRO CONTABLE", "/ ACCOUNTING REGISTER"),
        "h1": ("Transacciones — Resilience Brothers",
               "Transactions — Resilience Brothers"),
        "filters_label": ("Filtros →", "Filters →"),
        "f_direction": ("Dirección", "Direction"),
        "f_currency": ("Moneda", "Currency"),
        "f_holder": ("Titular", "Holder"),
        "f_since": ("Desde", "From"),
        "f_until": ("Hasta", "To"),
        "f_amount": ("Monto", "Amount"),
        "all": ("todas", "all"),
        "all_holders": ("todos", "all"),
        "amount_range_to": ("a", "to"),
        "totals_title": ("TOTALES POR MONEDA", "TOTALS PER CURRENCY"),
        "inflows": ("Entradas", "Inflows"),
        "outflows": ("Salidas", "Outflows"),
        "net": ("Neto", "Net"),
        "total_tx": ("Total de transacciones:", "Total transactions:"),
        "col_date": ("Fecha (UTC)", "Date (UTC)"),
        "col_type": ("Tipo", "Type"),
        "col_currency": ("Moneda", "Currency"),
        "col_amount": ("Monto", "Amount"),
        "col_holder": ("Titular cuenta", "Account holder"),
        "col_client": ("Cliente", "Client"),
        "col_method": ("Método", "Method"),
        "col_id": ("ID", "ID"),
        "row_in": ("↓ ENTRADA", "↓ INFLOW"),
        "row_out": ("↑ SALIDA", "↑ OUTFLOW"),
    }
    v = _STR.get(key, ("", ""))
    return v[1] if is_en else v[0]


def _header_footer_factory(lang: str):
    """Returns a `(canvas, doc)` callback with `lang` baked in — reportlab's
    callback signature can't accept extra args, so we close over `lang`."""
    def _draw(canvas, doc):
        canvas.saveState()
        w, h = landscape(LETTER)
        canvas.setFillColor(BG_DARK)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
        canvas.setFillColor(PANEL)
        canvas.rect(0, h - 64, w, 64, fill=1, stroke=0)
        if LOGO_PATH.exists():
            try:
                canvas.drawImage(str(LOGO_PATH), 32, h - 58, width=46, height=46,
                                 preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        canvas.setFillColor(TEXT)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(88, h - 28, "RESILIENCE BROTHERS")
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(88, h - 42, _t("subtitle", lang))
        canvas.setFillColor(BRAND_PURPLE)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(w - 36, h - 28, _t("header_tag", lang))
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(w - 36, h - 42, _t("header_sub", lang))
        gen_ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        canvas.drawString(36, 20, f"{_t('generated', lang)} {gen_ts}")
        canvas.drawCentredString(w / 2, 20, "resiliencebrothers.com")
        canvas.drawRightString(w - 36, 20, f"{_t('page', lang)} {doc.page}")
        canvas.setStrokeColor(BORDER)
        canvas.line(36, 32, w - 36, 32)
        canvas.restoreState()
    return _draw


def _build_filters_paragraph(filters: dict, style: ParagraphStyle, lang: str) -> Paragraph:
    """Format the filter bar shown under the PDF title."""
    all_word = _t("all", lang)
    all_holders_word = _t("all_holders", lang)
    f_dir = filters.get("direction") or all_word
    f_cur = filters.get("currency") or all_word
    f_holder = filters.get("holder") or all_holders_word
    f_since = filters.get("since") or "—"
    f_until = filters.get("until") or "—"
    f_min = filters.get("min_amount")
    f_max = filters.get("max_amount")
    amount_range = "—"
    if f_min is not None or f_max is not None:
        to_word = _t("amount_range_to", lang)
        amount_range = f"{f_min if f_min is not None else '∞-'} {to_word} {f_max if f_max is not None else '+∞'}"
    return Paragraph(
        f"{_t('filters_label', lang)} {_t('f_direction', lang)}: <font color='#FFFFFF'><b>{f_dir}</b></font> · "
        f"{_t('f_currency', lang)}: <font color='#FFFFFF'><b>{f_cur}</b></font> · "
        f"{_t('f_holder', lang)}: <font color='#FFFFFF'><b>{f_holder}</b></font> · "
        f"{_t('f_since', lang)}: <font color='#FFFFFF'><b>{f_since}</b></font> · "
        f"{_t('f_until', lang)}: <font color='#FFFFFF'><b>{f_until}</b></font> · "
        f"{_t('f_amount', lang)}: <font color='#FFFFFF'><b>{amount_range}</b></font>",
        style,
    )


def _build_totals_paragraph(totals: dict, style: ParagraphStyle, lang: str) -> Paragraph | None:
    """Render per-currency in/out/net summary lines, or None when totals are empty."""
    by_cur = totals.get("by_currency", {})
    lines = []
    for code in sorted(by_cur.keys()):
        v = by_cur[code]
        in_amt = v.get("in", 0.0)
        out_amt = v.get("out", 0.0)
        net = in_amt - out_amt
        net_color = "#22C55E" if net >= 0 else "#EF4444"
        lines.append(
            f"<font color='#8B5CF6'><b>{code}</b></font>: "
            f"{_t('inflows', lang)} <font color='#22C55E'>+{in_amt:,.2f}</font> · "
            f"{_t('outflows', lang)} <font color='#EF4444'>-{out_amt:,.2f}</font> · "
            f"{_t('net', lang)} <font color='{net_color}'><b>{net:+,.2f}</b></font>"
        )
    if not lines:
        return None
    return Paragraph(f"<b>{_t('totals_title', lang)}</b><br/>" + "<br/>".join(lines), style)


def _format_entry_row(e: dict, lang: str) -> list[str]:
    """Convert one transaction entry into a table row (8 cols)."""
    try:
        ts = datetime.fromisoformat(e.get("created_at", "")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts = e.get("created_at", "—")
    is_in = e.get("direction") == "in"
    tipo = _t("row_in", lang) if is_in else _t("row_out", lang)
    return [
        ts,
        tipo,
        e.get("currency", "—"),
        f"{e.get('amount', 0):,.2f}",
        (e.get("holder_name") or "—")[:30],
        (e.get("client_name") or "—")[:24],
        e.get("method", "—"),
        (e.get("ref_id") or "—")[:8],
    ]


def _build_transactions_table(entries: list, lang: str) -> Table:
    """Assemble the full transactions table with directional colouring on `Tipo`."""
    headers = [
        _t("col_date", lang), _t("col_type", lang), _t("col_currency", lang),
        _t("col_amount", lang), _t("col_holder", lang), _t("col_client", lang),
        _t("col_method", lang), _t("col_id", lang),
    ]
    data = [headers] + [_format_entry_row(e, lang) for e in entries]
    if len(data) == 1:
        data.append(["—"] * 8)

    col_widths = [1.1*inch, 0.9*inch, 0.7*inch, 1.0*inch, 1.9*inch, 1.6*inch, 0.9*inch, 0.7*inch]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style: list = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
    ]
    for row_idx, entry in enumerate(entries, start=1):
        color = GREEN if entry.get("direction") == "in" else RED
        style.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), color))
        style.append(("FONTNAME", (1, row_idx), (1, row_idx), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style))
    return tbl


def generate_transactions_pdf(entries: list, filters: dict, totals: dict,
                               lang: str = "es") -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(LETTER),
        leftMargin=24, rightMargin=24, topMargin=80, bottomMargin=44,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], textColor=TEXT, fontSize=20, leading=22, fontName="Helvetica-Bold", spaceAfter=4)
    label = ParagraphStyle('label', parent=styles['Normal'], textColor=BRAND_PURPLE, fontSize=8, leading=10, fontName="Helvetica-Bold", spaceAfter=2)
    sub = ParagraphStyle('sub', parent=styles['Normal'], textColor=TEXT_MUTED, fontSize=9, leading=12, spaceAfter=10)
    totals_style = ParagraphStyle('totals', parent=styles['Normal'], textColor=TEXT, fontSize=10, leading=14, spaceAfter=14)

    story: list = [
        Paragraph(_t("eyebrow", lang), label),
        Paragraph(_t("h1", lang), h1),
        _build_filters_paragraph(filters, sub, lang),
    ]
    totals_para = _build_totals_paragraph(totals, totals_style, lang)
    if totals_para is not None:
        story.append(totals_para)
    story.append(Paragraph(
        f"{_t('total_tx', lang)} <font color='#8B5CF6'><b>{len(entries)}</b></font>",
        sub,
    ))
    story.append(_build_transactions_table(entries, lang))
    story.append(Spacer(1, 14))

    hf = _header_footer_factory(lang)
    doc.build(story, onFirstPage=hf, onLaterPages=hf)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
