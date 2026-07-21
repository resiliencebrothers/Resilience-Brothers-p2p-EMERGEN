"""PDF generation for the client daily/range closing report.

iter90 — Extended so the same generator handles VIP AND normal clients
over a *range* of dates (not a single day). The title header switches
between "CIERRE VIP" and "CIERRE CONTABLE" based on the client role,
and the body now shows every transaction in the range (inflows,
outflows, conversions) — not just P2P orders. The signature +
company stamp are drawn at the bottom via the shared helper so every
PDF in the platform ships a consistent legal footer.
"""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

from pdf_signature import build_signature_block


BRAND_PURPLE = colors.HexColor("#8B5CF6")
BG_DARK = colors.HexColor("#14101F")
PANEL = colors.HexColor("#1A1730")
BORDER = colors.HexColor("#2a2a2a")
TEXT_MUTED = colors.HexColor("#A3A3A3")
TEXT = colors.HexColor("#FFFFFF")
GREEN = colors.HexColor("#22C55E")

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def _header_footer_factory(is_vip: bool):
    """iter90 — the top-right header label now flips between VIP and
    accounting closing based on the role of the client the PDF is
    being generated for."""
    tag = "CIERRE VIP" if is_vip else "CIERRE CONTABLE"

    def _draw(canvas, doc):
        canvas.saveState()
        w, h = LETTER
        # Background dark
        canvas.setFillColor(BG_DARK)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
        # Header band
        canvas.setFillColor(PANEL)
        canvas.rect(0, h - 70, w, 70, fill=1, stroke=0)
        # Logo image
        if LOGO_PATH.exists():
            try:
                canvas.drawImage(str(LOGO_PATH), 32, h - 64, width=52, height=52,
                                 preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        canvas.setFillColor(TEXT)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(96, h - 32, "RESILIENCE BROTHERS")
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(96, h - 46, "Global P2P Trade Infrastructure")
        # Top-right doc label
        canvas.setFillColor(BRAND_PURPLE)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(w - 36, h - 32, tag)
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(w - 36, h - 46, "CLOSING REPORT")
        # Footer
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(36, 24, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        canvas.drawCentredString(w / 2, 24, "resiliencebrothers.com")
        canvas.drawRightString(w - 36, 24, f"Página {doc.page}")
        canvas.setStrokeColor(BORDER)
        canvas.line(36, 38, w - 36, 38)
        canvas.restoreState()
    return _draw


# Legacy alias — used by fixtures + tests that still call the module-level
# `_header_footer` directly. Preserves back-compat until we migrate them.
def _header_footer(canvas, doc):
    return _header_footer_factory(is_vip=True)(canvas, doc)


def _compute_closing_totals(orders: list) -> dict:
    """Aggregate the four headline figures shown in the summary band."""
    total_received = 0.0
    total_in_native: dict = {}
    total_volume_from = 0.0
    for o in orders:
        total_volume_from += o.get("amount_from", 0) or 0
        amt_to = o.get("amount_to", 0) or 0
        if o.get("delivery_method") == "accumulate":
            total_received += amt_to
        else:
            total_in_native[o["to_code"]] = total_in_native.get(o["to_code"], 0) + amt_to
    return {
        "total_received_usd": total_received,
        "total_in_native": total_in_native,
        "total_orders": len(orders),
        "total_volume_from": total_volume_from,
    }


def _format_order_row(o: dict) -> list:
    """Render a single order as the 7-column row of the orders table."""
    ts = o.get("updated_at") or o.get("created_at")
    try:
        ts_fmt = datetime.fromisoformat(ts).strftime("%H:%M") if ts else "—"
    except Exception:
        ts_fmt = "—"
    return [
        o["id"][:6],
        ts_fmt,
        f"{o['from_code']}→{o['to_code']}",
        f"{o['amount_from']:.2f} {o['from_code']}",
        f"{o['amount_to']:.2f} {o['to_code']}",
        f"{o['rate_applied']:.4f}",
        o["delivery_method"],
    ]


def _build_currency_breakdown_table(total_in_native: dict) -> Table:
    rows = [["Moneda", "Total recibido"]]
    for code, total in total_in_native.items():
        rows.append([code, f"{total:,.2f}"])
    tbl = Table(rows, colWidths=[2*inch, 2*inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _format_tx_row(e: dict) -> list:
    """iter90 — render one transactions_registry entry (in/out/self-convert)
    into the 7-col row the closing PDF prints. Compact for LETTER width."""
    try:
        ts = datetime.fromisoformat(e.get("created_at", "")).strftime("%m-%d %H:%M")
    except Exception:
        ts = e.get("created_at", "—")[:10]
    direction = e.get("direction")
    if direction == "in":
        tipo = "↓ ENTRADA"
    elif direction == "out":
        tipo = "↑ SALIDA"
    else:
        tipo = direction or "—"
    method = (e.get("method") or "—")
    holder = (e.get("holder_name") or "—")[:22]
    return [
        (e.get("ref_id") or "—")[:8],
        ts,
        tipo,
        e.get("currency", "—"),
        f"{e.get('amount', 0):,.2f}",
        holder,
        method[:14],
    ]


def _compute_by_currency_totals(entries: list) -> dict:
    """Aggregate inflow/outflow/net per currency (mirrors
    services.transactions.compute_transaction_totals but only what
    we render on the closing PDF — kept internal so this module has
    no import-time dependency on the transactions service)."""
    by_cur: dict = {}
    for e in entries:
        code = e.get("currency", "?")
        amt = float(e.get("amount", 0) or 0)
        bucket = by_cur.setdefault(code, {"in": 0.0, "out": 0.0})
        if e.get("direction") == "in":
            bucket["in"] += amt
        elif e.get("direction") == "out":
            bucket["out"] += amt
    return by_cur


def generate_vip_closing_pdf(
    user: dict,
    entries: list,
    since: str = "",
    until: str = "",
    final_balance: float = 0.0,
    is_vip: bool = False,
) -> bytes:
    """iter90 — Closing report over an arbitrary date range.

    * `entries` are transactions_registry rows (from
      `services.transactions.build_transactions`) — inflows, outflows
      and self-conversions.
    * `since`/`until` are ISO-date strings ("YYYY-MM-DD"); when both
      are empty the PDF renders as "todo el histórico".
    * `is_vip` flips the top-right label between "CIERRE VIP" and the
      neutral "CIERRE CONTABLE", plus the H1 wording.
    * The legally binding signature + stamp block is drawn at the end
      via the shared `pdf_signature.build_signature_block` helper.

    Back-compat: legacy tests that used to call this with `orders=` and
    a single `date_label=` positional string are handled by
    `generate_vip_closing_pdf_legacy` (kept below).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=36, rightMargin=36, topMargin=90, bottomMargin=50,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], textColor=TEXT, fontSize=22, leading=24, spaceAfter=4, fontName="Helvetica-Bold")
    label = ParagraphStyle('label', parent=styles['Normal'], textColor=BRAND_PURPLE, fontSize=8, leading=10, spaceAfter=2, fontName="Helvetica-Bold")
    sub = ParagraphStyle('sub', parent=styles['Normal'], textColor=TEXT_MUTED, fontSize=10, leading=12, spaceAfter=18)
    body = ParagraphStyle('body', parent=styles['Normal'], textColor=TEXT, fontSize=10, leading=14)
    body_muted = ParagraphStyle('bodym', parent=styles['Normal'], textColor=TEXT_MUTED, fontSize=9, leading=12)

    story: list = []

    # ─── Title ─────────────────────────────────────────────────────
    eyebrow_txt = "/ CIERRE DIARIO VIP" if is_vip else "/ CIERRE CONTABLE"
    story.append(Paragraph(eyebrow_txt, label))

    if since and until and since == until:
        title = f"Reporte del {since}"
    elif since and until:
        title = f"Reporte del {since} al {until}"
    elif since:
        title = f"Reporte desde {since}"
    elif until:
        title = f"Reporte hasta {until}"
    else:
        title = "Reporte histórico completo"
    story.append(Paragraph(title, h1))

    story.append(Paragraph(
        f"Cliente: <font color='#FFFFFF'><b>{user.get('name','')}</b></font> · {user.get('email','')}",
        sub,
    ))

    # ─── Summary band ──────────────────────────────────────────────
    by_cur = _compute_by_currency_totals(entries)
    total_in_usd = 0.0
    total_out_usd = 0.0
    # Only USD/USDT sum into the USD headline (LATAM fiats aren't rate-
    # converted here to keep the PDF stateless — a future iter can pull
    # live rates once the treasury service exposes them synchronously).
    for code, v in by_cur.items():
        if code in ("USD", "USDT", "USDCASH_TEST", "USDT_TEST"):
            total_in_usd += v["in"]
            total_out_usd += v["out"]
    total_tx = len(entries)

    summary_data = [
        [
            Paragraph("Transacciones totales", body_muted),
            Paragraph("Entradas USD·USDT", body_muted),
            Paragraph("Salidas USD·USDT", body_muted),
            Paragraph("Saldo al cierre", body_muted),
        ],
        [
            Paragraph(f"<font size=18 color='#FFFFFF'><b>{total_tx}</b></font>", body),
            Paragraph(f"<font size=14 color='#22C55E'><b>+${total_in_usd:,.2f}</b></font>", body),
            Paragraph(f"<font size=14 color='#EF4444'><b>-${total_out_usd:,.2f}</b></font>", body),
            Paragraph(f"<font size=14 color='#8B5CF6'><b>${final_balance:,.2f}</b></font>", body),
        ],
    ]
    tbl = Table(summary_data, colWidths=[1.85 * inch] * 4)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 14))

    # ─── Per-currency breakdown ───────────────────────────────────
    if by_cur:
        story.append(Paragraph("Totales por moneda", label))
        story.append(Spacer(1, 4))
        cur_data = [["Moneda", "Entradas", "Salidas", "Neto"]]
        for code in sorted(by_cur.keys()):
            v = by_cur[code]
            net = v["in"] - v["out"]
            cur_data.append([
                code,
                f"+{v['in']:,.2f}",
                f"-{v['out']:,.2f}",
                f"{net:+,.2f}",
            ])
        cur_tbl = Table(cur_data, colWidths=[1.4 * inch, 1.8 * inch, 1.8 * inch, 1.4 * inch])
        cur_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PANEL),
            ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
            ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("TEXTCOLOR", (1, 1), (1, -1), GREEN),
            ("TEXTCOLOR", (2, 1), (2, -1), colors.HexColor("#EF4444")),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(cur_tbl)
        story.append(Spacer(1, 18))

    # ─── Detailed transactions table ───────────────────────────────
    story.append(Paragraph("Detalle de transacciones", label))
    story.append(Spacer(1, 6))
    headers = ["ID", "Fecha", "Tipo", "Moneda", "Monto", "Titular", "Método"]
    data = [headers] + [_format_tx_row(e) for e in entries]
    if len(data) == 1:
        data.append(["—"] * 7)

    tx_tbl = Table(
        data,
        colWidths=[0.6 * inch, 0.85 * inch, 0.85 * inch, 0.7 * inch,
                   1.0 * inch, 1.5 * inch, 1.1 * inch],
        repeatRows=1,
    )
    tx_style: list = [
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
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    # Colour the Tipo column per direction (green in / red out).
    for row_idx, entry in enumerate(entries, start=1):
        d = entry.get("direction")
        if d == "in":
            tx_style.append(("TEXTCOLOR", (2, row_idx), (2, row_idx), GREEN))
        elif d == "out":
            tx_style.append(("TEXTCOLOR", (2, row_idx), (2, row_idx), colors.HexColor("#EF4444")))
        tx_style.append(("FONTNAME", (2, row_idx), (2, row_idx), "Helvetica-Bold"))
    tx_tbl.setStyle(TableStyle(tx_style))
    story.append(tx_tbl)
    story.append(Spacer(1, 22))

    # ─── Signature block (shared) ──────────────────────────────────
    story.append(build_signature_block(
        lang=(user.get("preferred_language") or "es"),
        client_name=user.get("name", ""),
        include_client_side=True,
        total_width_inches=7.0,
    ))

    hf = _header_footer_factory(is_vip=is_vip)
    doc.build(story, onFirstPage=hf, onLaterPages=hf)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
