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


BRAND_PURPLE = colors.HexColor("#8B5CF6")
BG_DARK = colors.HexColor("#0A0A0F")
PANEL = colors.HexColor("#141322")
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
