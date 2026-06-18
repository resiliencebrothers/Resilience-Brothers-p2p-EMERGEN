"""Revenue time-series aggregation + CSV/PDF export helpers (admin)."""
from io import BytesIO, StringIO
from pathlib import Path
import csv
from collections import OrderedDict
from datetime import datetime, timezone
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


BRAND_YELLOW = colors.HexColor("#EAB308")
BG_DARK = colors.HexColor("#0A0A0A")
PANEL = colors.HexColor("#141414")
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


def build_buckets(orders, redemptions, profit_per_order_usdt, granularity: str):
    """Group orders + delivered redemptions into day/month buckets.

    profit_per_order_usdt: dict mapping order_id -> profit_usdt (already computed by caller).
    Returns sorted list (most recent first) of dicts with: bucket, label,
    p2p_profit_usdt, marketplace_profit_usdt, total_profit_usdt, orders, deliveries, volume_usdt.
    """
    buckets: dict = {}

    def _ensure(key):
        if key not in buckets:
            buckets[key] = {
                "bucket": key,
                "p2p_profit_usdt": 0.0,
                "marketplace_profit_usdt": 0.0,
                "total_profit_usdt": 0.0,
                "orders": 0,
                "deliveries": 0,
                "volume_usdt": 0.0,
            }
        return buckets[key]

    for o in orders:
        ts = o.get("updated_at") or o.get("created_at") or ""
        key = _bucket_key(ts, granularity)
        b = _ensure(key)
        b["orders"] += 1
        # Caller pre-computes volume in USDT and stores under o["_volume_usdt"]
        b["volume_usdt"] += float(o.get("_volume_usdt") or 0.0)
        prof = float(profit_per_order_usdt.get(o["id"], 0.0))
        b["p2p_profit_usdt"] += prof
        b["total_profit_usdt"] += prof

    for r in redemptions:
        ts = r.get("created_at") or ""
        key = _bucket_key(ts, granularity)
        b = _ensure(key)
        b["deliveries"] += 1
        prof = float(r.get("total_usd") or 0.0) - float(r.get("cost_usd") or 0.0)
        b["marketplace_profit_usdt"] += prof
        b["total_profit_usdt"] += prof

    rows = []
    for v in buckets.values():
        for k in ("p2p_profit_usdt", "marketplace_profit_usdt", "total_profit_usdt", "volume_usdt"):
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
                "Ganancia Marketplace (USDT)", "Ganancia Total (USDT)"])
    tot_p2p = tot_mkt = tot_total = tot_vol = 0.0
    tot_ords = 0
    for r in rows:
        tot_p2p += r["p2p_profit_usdt"]
        tot_mkt += r["marketplace_profit_usdt"]
        tot_total += r["total_profit_usdt"]
        tot_vol += r["volume_usdt"]
        tot_ords += r["orders"]
        w.writerow([
            r["bucket"],
            r["orders"],
            f"{r['volume_usdt']:.4f}",
            f"{r['p2p_profit_usdt']:.4f}",
            f"{r['marketplace_profit_usdt']:.4f}",
            f"{r['total_profit_usdt']:.4f}",
        ])
    w.writerow([])
    w.writerow(["TOTAL", tot_ords, f"{tot_vol:.4f}", f"{tot_p2p:.4f}",
                f"{tot_mkt:.4f}", f"{tot_total:.4f}"])
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
    canvas.setFillColor(BRAND_YELLOW)
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
                         fontName="Helvetica-Bold", fontSize=14, textColor=BRAND_YELLOW)

    story = [
        Paragraph("Ganancia Mensual", title),
        Paragraph(f"Período: <b>{period_label}</b>", meta),
        Spacer(1, 12),
    ]

    # Totals card
    totals_data = [[
        Paragraph("Ganancia P2P", meta),
        Paragraph("Ganancia Marketplace", meta),
        Paragraph("Ganancia Total", meta),
        Paragraph("Volumen", meta),
        Paragraph("Órdenes", meta),
    ], [
        Paragraph(f"{totals['p2p']:.2f} USDT", big),
        Paragraph(f"{totals['marketplace']:.2f} USDT", big),
        Paragraph(f"{totals['total']:.2f} USDT", big),
        Paragraph(f"{totals['volume']:.2f} USDT", big),
        Paragraph(f"{totals['orders']}", big),
    ]]
    tbl = Table(totals_data, colWidths=[1.5*inch]*5)
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

    # Daily table
    head = ["Fecha", "Órdenes", "Volumen USDT", "P2P", "Marketplace", "Total"]
    data = [head]
    for r in rows:
        data.append([
            r["bucket"],
            str(r["orders"]),
            f"{r['volume_usdt']:.2f}",
            f"{r['p2p_profit_usdt']:.2f}",
            f"{r['marketplace_profit_usdt']:.2f}",
            f"{r['total_profit_usdt']:.2f}",
        ])
    tbl2 = Table(data, colWidths=[1.2*inch, 0.8*inch, 1.2*inch, 1.0*inch, 1.3*inch, 1.0*inch])
    tbl2.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND_YELLOW),
        ("TEXTCOLOR", (0,0), (-1,0), BG_DARK),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND", (0,1), (-1,-1), PANEL),
        ("TEXTCOLOR", (0,1), (-1,-1), TEXT),
        ("TEXTCOLOR", (5,1), (5,-1), GREEN),  # total column green
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
