"""Revenue time-series aggregation + CSV/PDF export helpers (admin)."""
from io import BytesIO, StringIO
from pathlib import Path
import csv
from datetime import datetime, timezone
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Line, String, Rect
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker

from pdf_signature import build_signature_block


BRAND_PURPLE = colors.HexColor("#8B5CF6")
BG_DARK = colors.HexColor("#14101F")
PANEL = colors.HexColor("#1A1730")
BORDER = colors.HexColor("#2a2a2a")
TEXT_MUTED = colors.HexColor("#A3A3A3")
TEXT = colors.HexColor("#FFFFFF")
GREEN = colors.HexColor("#22C55E")

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def _bucket_key(iso_str: str, granularity: str) -> str:
    """Return YYYY-MM-DD for 'day' or YYYY-MM for 'month' from an ISO timestamp."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return "—"
    return dt.strftime("%Y-%m-%d") if granularity == "day" else dt.strftime("%Y-%m")


def _new_bucket(key: str) -> dict:
    return {
        "bucket": key,
        "p2p_profit_usdt": 0.0,
        "marketplace_profit_usdt": 0.0,
        "conversion_fees_usdt": 0.0,
        "total_profit_usdt": 0.0,
        "orders": 0,
        "deliveries": 0,
        "conversions": 0,
        "volume_usdt": 0.0,
    }


def _accumulate_orders(buckets: dict, orders, profit_per_order_usdt, granularity: str) -> None:
    for o in orders:
        ts = o.get("updated_at") or o.get("created_at") or ""
        b = buckets.setdefault(_bucket_key(ts, granularity), _new_bucket(_bucket_key(ts, granularity)))
        b["orders"] += 1
        b["volume_usdt"] += float(o.get("_volume_usdt") or 0.0)
        prof = float(profit_per_order_usdt.get(o["id"], 0.0))
        b["p2p_profit_usdt"] += prof
        b["total_profit_usdt"] += prof


def _accumulate_redemptions(buckets: dict, redemptions, granularity: str) -> None:
    for r in redemptions:
        ts = r.get("created_at") or ""
        b = buckets.setdefault(_bucket_key(ts, granularity), _new_bucket(_bucket_key(ts, granularity)))
        b["deliveries"] += 1
        prof = float(r.get("total_usd") or 0.0) - float(r.get("cost_usd") or 0.0)
        b["marketplace_profit_usdt"] += prof
        b["total_profit_usdt"] += prof


def _accumulate_conversion_fees(buckets: dict, fee_entries, granularity: str) -> None:
    """iter55.28 — bucket the 0.01 USDT conversion fees per period."""
    for row in fee_entries or []:
        ts = row.get("created_at") or ""
        b = buckets.setdefault(_bucket_key(ts, granularity), _new_bucket(_bucket_key(ts, granularity)))
        try:
            fee = float((row.get("details") or {}).get("usdt_fee") or 0.0)
        except (TypeError, ValueError):
            fee = 0.0
        if fee <= 0:
            continue
        b["conversions"] += 1
        b["conversion_fees_usdt"] += fee
        b["total_profit_usdt"] += fee


def build_buckets(orders, redemptions, profit_per_order_usdt, granularity: str,
                   conversion_fees: list = None):
    """Group orders + delivered redemptions + USDT conversion fees into
    day/month buckets.

    profit_per_order_usdt: dict mapping order_id -> profit_usdt.
    conversion_fees: optional list of `audit_log` rows for `vip.convert` with
                     `details.usdt_fee > 0` (iter55.28).
    Returns sorted list (most recent first) of per-period aggregates.
    """
    buckets: dict = {}
    _accumulate_orders(buckets, orders, profit_per_order_usdt, granularity)
    _accumulate_redemptions(buckets, redemptions, granularity)
    _accumulate_conversion_fees(buckets, conversion_fees, granularity)

    rows = []
    for v in buckets.values():
        for k in ("p2p_profit_usdt", "marketplace_profit_usdt",
                  "conversion_fees_usdt", "total_profit_usdt", "volume_usdt"):
            v[k] = round(v[k], 4)
        rows.append(v)
    rows.sort(key=lambda x: x["bucket"], reverse=True)
    return rows


# ---------------- CSV export ----------------

def revenue_monthly_csv(rows, period_label: str) -> bytes:
    """Generate a CSV for a monthly daily-breakdown.
    rows: list of daily buckets (one per day) sorted ascending by date.
    """
    buf = StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["RESILIENCE BROTHERS · Ganancia mensual"])
    w.writerow([f"Período: {period_label}"])
    w.writerow([f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"])
    w.writerow([])
    w.writerow(["Fecha", "Órdenes", "Volumen (USDT)", "Ganancia P2P (USDT)",
                "Ganancia Marketplace (USDT)", "Comisiones USDT",
                "Conversiones", "Ganancia Total (USDT)"])
    tot_p2p = tot_mkt = tot_fees = tot_total = tot_vol = 0.0
    tot_ords = tot_convs = 0
    for r in rows:
        tot_p2p += r["p2p_profit_usdt"]
        tot_mkt += r["marketplace_profit_usdt"]
        tot_fees += r.get("conversion_fees_usdt", 0.0)
        tot_total += r["total_profit_usdt"]
        tot_vol += r["volume_usdt"]
        tot_ords += r["orders"]
        tot_convs += r.get("conversions", 0)
        w.writerow([
            r["bucket"],
            r["orders"],
            f"{r['volume_usdt']:.4f}",
            f"{r['p2p_profit_usdt']:.4f}",
            f"{r['marketplace_profit_usdt']:.4f}",
            f"{r.get('conversion_fees_usdt', 0.0):.4f}",
            r.get("conversions", 0),
            f"{r['total_profit_usdt']:.4f}",
        ])
    w.writerow([])
    w.writerow(["TOTAL", tot_ords, f"{tot_vol:.4f}", f"{tot_p2p:.4f}",
                f"{tot_mkt:.4f}", f"{tot_fees:.4f}", tot_convs,
                f"{tot_total:.4f}"])
    return buf.getvalue().encode("utf-8-sig")


# ---------------- PDF export ----------------

def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = LETTER
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
    canvas.setFont("Helvetica", 8)
    canvas.drawString(88, h - 42, "Ganancia mensual · Auditoría contable interna")
    canvas.drawRightString(w - 32, h - 28,
                            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    canvas.setFillColor(BRAND_PURPLE)
    canvas.rect(0, h - 67, w, 2, fill=1, stroke=0)
    canvas.restoreState()


def revenue_monthly_pdf(rows, period_label: str, totals: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            topMargin=84, bottomMargin=48,
                            leftMargin=36, rightMargin=36)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"],
                            fontName="Helvetica-Bold", fontSize=16, textColor=TEXT, spaceAfter=4)
    meta = ParagraphStyle("meta", parent=styles["Normal"],
                          fontName="Helvetica", fontSize=9, textColor=TEXT_MUTED)
    big = ParagraphStyle("big", parent=styles["Normal"],
                         fontName="Helvetica-Bold", fontSize=14, textColor=BRAND_PURPLE)

    story = [
        Paragraph("Ganancia Mensual", title),
        Paragraph(f"Período: <b>{period_label}</b>", meta),
        Spacer(1, 12),
    ]

    # Totals card
    totals_data = [[
        Paragraph("Ganancia P2P", meta),
        Paragraph("Marketplace", meta),
        Paragraph("Comisiones USDT", meta),
        Paragraph("Ganancia Total", meta),
        Paragraph("Volumen", meta),
        Paragraph("Órdenes", meta),
    ], [
        Paragraph(f"{totals['p2p']:.2f} USDT", big),
        Paragraph(f"{totals['marketplace']:.2f} USDT", big),
        Paragraph(f"{totals.get('conversion_fees', 0.0):.2f} USDT", big),
        Paragraph(f"{totals['total']:.2f} USDT", big),
        Paragraph(f"{totals['volume']:.2f} USDT", big),
        Paragraph(f"{totals['orders']}", big),
    ]]
    tbl = Table(totals_data, colWidths=[1.25*inch]*6)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), PANEL),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.5, BORDER),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 16))

    # Chart: daily bars + cumulative line (only when there is data)
    if rows:
        story.append(Paragraph("Tendencia diaria · Barras = ganancia del día · Línea = acumulado", meta))
        story.append(Spacer(1, 6))
        story.append(_revenue_chart(rows))
        story.append(Spacer(1, 14))

    # Daily table
    head = ["Fecha", "Órdenes", "Volumen USDT", "P2P", "Marketplace",
            "Fees USDT", "Total"]
    data = [head]
    for r in rows:
        data.append([
            r["bucket"],
            str(r["orders"]),
            f"{r['volume_usdt']:.2f}",
            f"{r['p2p_profit_usdt']:.2f}",
            f"{r['marketplace_profit_usdt']:.2f}",
            f"{r.get('conversion_fees_usdt', 0.0):.2f}",
            f"{r['total_profit_usdt']:.2f}",
        ])
    tbl2 = Table(data, colWidths=[1.1*inch, 0.7*inch, 1.1*inch, 0.9*inch,
                                    1.1*inch, 0.9*inch, 0.9*inch])
    tbl2.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND_PURPLE),
        ("TEXTCOLOR", (0,0), (-1,0), TEXT),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND", (0,1), (-1,-1), PANEL),
        ("TEXTCOLOR", (0,1), (-1,-1), TEXT),
        ("TEXTCOLOR", (6,1), (6,-1), GREEN),  # total column green
        ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ALIGN", (1,0), (-1,-1), "RIGHT"),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.25, BORDER),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(tbl2)
    story.append(Spacer(1, 22))
    story.append(build_signature_block(
        lang="es", include_client_side=False, total_width_inches=7.0,
    ))
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


def _revenue_chart(rows) -> Drawing:
    """Combined chart: vertical bars (daily profit) + cumulative line.

    Sorted by date ascending. X-axis labels show day-of-month (DD).
    """
    sorted_rows = sorted(rows, key=lambda x: x["bucket"])
    daily = [r["total_profit_usdt"] for r in sorted_rows]
    labels = [r["bucket"][-2:] for r in sorted_rows]  # DD only
    # Cumulative
    cum = []
    running = 0.0
    for v in daily:
        running += v
        cum.append(running)

    width = 7.0 * inch
    height = 2.4 * inch
    d = Drawing(width, height)
    # Background
    d.add(Rect(0, 0, width, height, fillColor=PANEL, strokeColor=BORDER, strokeWidth=0.5))

    # --- Bars ---
    bar = VerticalBarChart()
    bar.x = 40
    bar.y = 28
    bar.width = width - 70
    bar.height = height - 50
    bar.data = [daily]
    bar.categoryAxis.categoryNames = labels
    bar.categoryAxis.labels.fontSize = 6
    bar.categoryAxis.labels.fillColor = TEXT_MUTED
    bar.valueAxis.labels.fontSize = 6
    bar.valueAxis.labels.fillColor = TEXT_MUTED
    bar.bars[0].fillColor = BRAND_PURPLE
    bar.bars[0].strokeColor = None
    bar.barWidth = max(2, (bar.width / max(1, len(daily))) * 0.6)
    bar.valueAxis.gridStrokeColor = BORDER
    bar.valueAxis.gridStrokeWidth = 0.25
    bar.valueAxis.visibleGrid = True
    d.add(bar)

    # --- Cumulative line (overlaid, separate axis scale) ---
    # Map cumulative values onto bar.y / bar.height using its own min/max
    if cum:
        cmin = min(0.0, min(cum))
        cmax = max(0.0, max(cum)) or 1.0
        span = cmax - cmin or 1.0
        n = len(cum)
        line = LinePlot()
        line.x = bar.x
        line.y = bar.y
        line.width = bar.width
        line.height = bar.height
        # X positions: center of each bar slot
        step = bar.width / max(1, n)
        pts = []
        for i, v in enumerate(cum):
            px = (i + 0.5) * step
            py = ((v - cmin) / span) * bar.height
            pts.append((px, py))
        # Use absolute coords by setting plot ranges
        line.data = [pts]
        line.xValueAxis.valueMin = 0
        line.xValueAxis.valueMax = bar.width
        line.yValueAxis.valueMin = 0
        line.yValueAxis.valueMax = bar.height
        line.xValueAxis.visible = False
        line.yValueAxis.visible = False
        line.lines[0].strokeColor = GREEN
        line.lines[0].strokeWidth = 1.5
        line.lines[0].symbol = makeMarker("Circle", size=2, fillColor=GREEN, strokeColor=None)
        d.add(line)

    # Legend
    d.add(Rect(50, height - 18, 12, 6, fillColor=BRAND_PURPLE, strokeColor=None))
    d.add(String(66, height - 14, "Ganancia diaria",
                  fontSize=7, fillColor=TEXT_MUTED))
    d.add(Line(150, height - 15, 162, height - 15, strokeColor=GREEN, strokeWidth=1.5))
    d.add(String(166, height - 14, "Acumulado",
                  fontSize=7, fillColor=TEXT_MUTED))
    return d



# ---------------- Multi-month analytics report (iter55.36l) ----------------

def revenue_analytics_csv(monthly_rows, summary: dict, period_label: str) -> bytes:
    """CSV for the operator's "Estadísticas" analytics dialog. Includes:
      • a header block with the 3 top-line highlights + category totals
      • a monthly comparison table sorted DESC (freshest first)

    The two sections are separated by a blank line so spreadsheets keep them
    distinct. UTF-8 with BOM so Excel handles Spanish accents correctly.
    """
    buf = StringIO()
    w = csv.writer(buf)

    # --- Highlights block ---
    top_month = max(monthly_rows, key=lambda r: r.get("total_profit_usdt", 0),
                    default=None) if monthly_rows else None
    top_pair = (summary.get("by_pair") or [None])[0]

    cats = [
        ("Intercambio P2P",  summary.get("p2p_profit_usdt", 0.0)),
        ("Marketplace",      summary.get("marketplace_profit_usdt", 0.0)),
        ("Conversiones",     summary.get("conversion_fees_usdt", 0.0)),
    ]
    abs_total = sum(abs(v) for _, v in cats) or 1.0
    cats_sorted = sorted(cats, key=lambda x: abs(x[1]), reverse=True)

    w.writerow(["Reporte de Ingresos — Analítica comparativa"])
    w.writerow(["Período", period_label])
    w.writerow(["Generado", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")])
    w.writerow([])
    w.writerow(["Mejor mes",
                 top_month["bucket"] if top_month else "—",
                 f"{top_month['total_profit_usdt']:.2f} USDT" if top_month else ""])
    w.writerow(["Par con más ganancia",
                 top_pair["pair"] if top_pair else "—",
                 f"{top_pair['profit_usdt']:.2f} USDT" if top_pair else "",
                 f"{top_pair['orders']} órdenes" if top_pair else ""])
    w.writerow(["Categoría líder",
                 cats_sorted[0][0],
                 f"{cats_sorted[0][1]:.2f} USDT",
                 f"{(abs(cats_sorted[0][1]) / abs_total * 100):.1f}%"])
    w.writerow([])
    w.writerow(["Aporte por categoría", "USDT", "% (magnitud)"])
    for name, val in cats_sorted:
        share = abs(val) / abs_total * 100
        w.writerow([name, f"{val:.2f}", f"{share:.1f}%"])
    w.writerow([])

    # --- Monthly table ---
    w.writerow(["Mes", "P2P (USDT)", "Marketplace (USDT)",
                "Conversiones (USDT)", "Total (USDT)", "Órdenes"])
    for r in sorted(monthly_rows, key=lambda x: x["bucket"], reverse=True):
        w.writerow([
            r["bucket"],
            f"{r.get('p2p_profit_usdt', 0.0):.2f}",
            f"{r.get('marketplace_profit_usdt', 0.0):.2f}",
            f"{r.get('conversion_fees_usdt', 0.0):.2f}",
            f"{r.get('total_profit_usdt', 0.0):.2f}",
            r.get("orders", 0),
        ])
    return buf.getvalue().encode("utf-8-sig")


def _analytics_bars(monthly_rows) -> Drawing:
    """Stacked bar chart of the last-12 months revenue broken down by
    category (P2P / Marketplace / Conversions). Mirrors the on-screen
    recharts view in `RevenueAnalyticsDialog.jsx`."""
    rows = sorted(monthly_rows, key=lambda x: x["bucket"])[-12:]
    labels = [r["bucket"] for r in rows]
    p2p  = [r.get("p2p_profit_usdt", 0.0) for r in rows]
    mkt  = [r.get("marketplace_profit_usdt", 0.0) for r in rows]
    conv = [r.get("conversion_fees_usdt", 0.0) for r in rows]

    width = 7.0 * inch
    height = 2.6 * inch
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=PANEL,
               strokeColor=BORDER, strokeWidth=0.5))

    if not rows:
        d.add(String(width / 2, height / 2, "Sin datos mensuales aún.",
                     fontSize=10, fillColor=TEXT_MUTED, textAnchor="middle"))
        return d

    bar = VerticalBarChart()
    bar.x = 44
    bar.y = 32
    bar.width = width - 80
    bar.height = height - 60
    bar.data = [p2p, mkt, conv]
    bar.categoryAxis.categoryNames = labels
    bar.categoryAxis.labels.fontSize = 6
    bar.categoryAxis.labels.fillColor = TEXT_MUTED
    bar.categoryAxis.labels.angle = 25
    bar.categoryAxis.labels.dy = -6
    bar.valueAxis.labels.fontSize = 6
    bar.valueAxis.labels.fillColor = TEXT_MUTED
    bar.valueAxis.gridStrokeColor = BORDER
    bar.valueAxis.gridStrokeWidth = 0.25
    bar.valueAxis.visibleGrid = True
    bar.bars[0].fillColor = BRAND_PURPLE               # P2P
    bar.bars[0].strokeColor = None
    bar.bars[1].fillColor = GREEN                      # Marketplace
    bar.bars[1].strokeColor = None
    bar.bars[2].fillColor = colors.HexColor("#EAB308") # Conversiones
    bar.bars[2].strokeColor = None
    # Stacking MUST be set AFTER per-bar fillColor — reportlab's ChartMixin
    # eagerly recomputes bar handles when `categoryAxis.style` flips, and
    # accessing `bar.bars[i]` after that mutation locks up the interpreter.
    # Do NOT iterate `for b in bar.bars` either — the special `bars` accessor
    # entered a loop for us during testing.
    bar.categoryAxis.style = "stacked"
    d.add(bar)

    # Legend
    legend_y = height - 16
    d.add(Rect(46, legend_y, 10, 6, fillColor=BRAND_PURPLE, strokeColor=None))
    d.add(String(60, legend_y + 1, "P2P", fontSize=7, fillColor=TEXT_MUTED))
    d.add(Rect(94, legend_y, 10, 6, fillColor=GREEN, strokeColor=None))
    d.add(String(108, legend_y + 1, "Marketplace", fontSize=7, fillColor=TEXT_MUTED))
    d.add(Rect(174, legend_y, 10, 6,
                fillColor=colors.HexColor("#EAB308"), strokeColor=None))
    d.add(String(188, legend_y + 1, "Conversiones", fontSize=7, fillColor=TEXT_MUTED))
    return d


def revenue_analytics_pdf(monthly_rows, summary: dict, period_label: str) -> bytes:
    """PDF for the operator's "Estadísticas" analytics dialog. Layout:
      1. Highlights strip (mejor mes · categoría líder · par top)
      2. Category breakdown table with magnitude-share %
      3. Stacked bar chart per month
      4. Monthly comparison table sorted DESC
    Uses the same brand palette as the on-screen dialog for consistency.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            topMargin=84, bottomMargin=48,
                            leftMargin=36, rightMargin=36)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"],
                            fontName="Helvetica-Bold", fontSize=16,
                            textColor=TEXT, spaceAfter=4)
    meta = ParagraphStyle("meta", parent=styles["Normal"],
                          fontName="Helvetica", fontSize=9, textColor=TEXT_MUTED)
    big = ParagraphStyle("big", parent=styles["Normal"],
                         fontName="Helvetica-Bold", fontSize=14,
                         textColor=BRAND_PURPLE)

    story = [
        Paragraph("Estadísticas comparativas de ingresos", title),
        Paragraph(f"Período: <b>{period_label}</b>", meta),
        Spacer(1, 12),
    ]

    top_month = max(monthly_rows, key=lambda r: r.get("total_profit_usdt", 0),
                    default=None) if monthly_rows else None
    top_pair = (summary.get("by_pair") or [None])[0]

    cats = [
        ("Intercambio P2P",  summary.get("p2p_profit_usdt", 0.0)),
        ("Marketplace",      summary.get("marketplace_profit_usdt", 0.0)),
        ("Conversiones",     summary.get("conversion_fees_usdt", 0.0)),
    ]
    abs_total = sum(abs(v) for _, v in cats) or 1.0
    cats_sorted = sorted(cats, key=lambda x: abs(x[1]), reverse=True)

    # --- Highlights strip ---
    hl_rows = [[
        Paragraph("Mejor mes", meta),
        Paragraph("Categoría líder", meta),
        Paragraph("Par con más ganancia", meta),
    ], [
        Paragraph(top_month["bucket"] if top_month else "—", big),
        Paragraph(cats_sorted[0][0] if cats_sorted else "—", big),
        Paragraph(top_pair["pair"] if top_pair else "—", big),
    ], [
        Paragraph(f"{top_month['total_profit_usdt']:.2f} USDT" if top_month else "sin datos", meta),
        Paragraph(f"{cats_sorted[0][1]:.2f} USDT · {abs(cats_sorted[0][1]) / abs_total * 100:.1f}%"
                  if cats_sorted else "", meta),
        Paragraph(f"{top_pair['profit_usdt']:.2f} USDT · {top_pair['orders']} órdenes"
                  if top_pair else "", meta),
    ]]
    hl = Table(hl_rows, colWidths=[2.4*inch, 2.4*inch, 2.4*inch])
    hl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), PANEL),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.5, BORDER),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(hl)
    story.append(Spacer(1, 14))

    # --- Category breakdown table ---
    cat_data = [["Categoría", "USDT", "% magnitud"]]
    for name, val in cats_sorted:
        share = abs(val) / abs_total * 100
        cat_data.append([name, f"{val:.2f}", f"{share:.1f}%"])
    cat_tbl = Table(cat_data, colWidths=[3.0*inch, 2.0*inch, 2.2*inch])
    cat_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND_PURPLE),
        ("TEXTCOLOR", (0,0), (-1,0), TEXT),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND", (0,1), (-1,-1), PANEL),
        ("TEXTCOLOR", (0,1), (-1,-1), TEXT),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ALIGN", (1,0), (-1,-1), "RIGHT"),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.25, BORDER),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(cat_tbl)
    story.append(Spacer(1, 14))

    # --- Monthly bar chart ---
    story.append(Paragraph("Ganancias por mes · barras apiladas", meta))
    story.append(Spacer(1, 6))
    story.append(_analytics_bars(monthly_rows))
    story.append(Spacer(1, 14))

    # --- Monthly comparison table (DESC) ---
    head = ["Mes", "P2P", "Marketplace", "Conversiones", "Total", "Órdenes"]
    data = [head]
    for r in sorted(monthly_rows, key=lambda x: x["bucket"], reverse=True):
        data.append([
            r["bucket"],
            f"{r.get('p2p_profit_usdt', 0.0):.2f}",
            f"{r.get('marketplace_profit_usdt', 0.0):.2f}",
            f"{r.get('conversion_fees_usdt', 0.0):.2f}",
            f"{r.get('total_profit_usdt', 0.0):.2f}",
            str(r.get("orders", 0)),
        ])
    mtbl = Table(data, colWidths=[1.1*inch, 1.1*inch, 1.3*inch, 1.4*inch,
                                    1.1*inch, 0.8*inch])
    mtbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND_PURPLE),
        ("TEXTCOLOR", (0,0), (-1,0), TEXT),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND", (0,1), (-1,-1), PANEL),
        ("TEXTCOLOR", (0,1), (-1,-1), TEXT),
        ("TEXTCOLOR", (4,1), (4,-1), GREEN),
        ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ALIGN", (1,0), (-1,-1), "RIGHT"),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.25, BORDER),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(mtbl)
    story.append(Spacer(1, 22))
    story.append(build_signature_block(
        lang="es", include_client_side=False, total_width_inches=7.0,
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
