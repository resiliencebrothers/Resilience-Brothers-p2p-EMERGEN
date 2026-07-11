"""iter55.17 — Monthly audit PDF export.

Produces a professional monthly audit report with:
- Executive Summary (period · total actions · KPIs by group · top actors ·
  anti-fraud signals · permission-scope distribution)
- Detailed chronological table of every audit entry in that month
- Integrity signature (SHA-256 of the canonical projection) — tamper-evident

The visual chrome mirrors `audit_pdf.py` (same header/footer/branding) so an
operator archiving both files sees a cohesive dossier.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether,
)


BRAND_PURPLE = colors.HexColor("#8B5CF6")
BG_DARK = colors.HexColor("#14101F")
PANEL = colors.HexColor("#1A1730")
BORDER = colors.HexColor("#2a2a2a")
TEXT_MUTED = colors.HexColor("#A3A3A3")
TEXT = colors.HexColor("#FFFFFF")
ACCENT_GREEN = colors.HexColor("#22C55E")
ACCENT_RED = colors.HexColor("#EF4444")

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


# ============================================================
# Header / Footer (matches audit_pdf.py chrome)
# ============================================================

def _header_footer(canvas, doc):
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
    canvas.drawString(88, h - 42, "Reporte mensual de auditoría — uso interno")
    canvas.setFillColor(BRAND_PURPLE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawRightString(w - 36, h - 28, "AUDIT · MENSUAL")
    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 36, h - 42, "COMPLIANCE · TRAZABILIDAD")
    canvas.drawString(36, 20, f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    canvas.drawCentredString(w / 2, 20, "resiliencebrothers.com")
    canvas.drawRightString(w - 36, 20, f"Página {doc.page}")
    canvas.setStrokeColor(BORDER)
    canvas.line(36, 32, w - 36, 32)
    canvas.restoreState()


# ============================================================
# Executive summary builders
# ============================================================

def _kpi_card(label: str, value: str, styles) -> Table:
    """Small stacked card (label above value) used in the summary strip."""
    label_p = Paragraph(f"<font color='#8B5CF6'>{label}</font>", styles["kpi_label"])
    value_p = Paragraph(f"<font color='#FFFFFF'>{value}</font>", styles["kpi_value"])
    inner = Table([[label_p], [value_p]], colWidths=[2.4 * inch])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0c0c0c")),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return inner


def _summary_strip(kpis: Dict[str, Any], styles) -> Table:
    """4 KPI cards in one row — the eye-catch header of the summary."""
    perm = kpis.get("permission_scope") or {}
    admin = perm.get("admin", 0)
    scoped = perm.get("scoped", 0)
    staff_def = perm.get("staff_default", 0) + perm.get("legacy", 0)
    anti = sum(item["count"] for item in (kpis.get("anti_fraud") or []))
    row = [
        _kpi_card("ACCIONES TOTALES", str(kpis.get("total_actions", 0)), styles),
        _kpi_card("ACTORES DISTINTOS", str(kpis.get("distinct_actors", 0)), styles),
        _kpi_card("SEÑALES ANTI-FRAUDE", str(anti), styles),
        _kpi_card("DISTRIBUCIÓN ROL",
                  f"A:{admin} · S:{staff_def} · L:{scoped}", styles),
    ]
    outer = Table([row], colWidths=[2.6 * inch] * 4)
    outer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def _table_by_group(kpis: Dict[str, Any], styles) -> Table:
    header = ["Categoría", "Código", "Acciones", "% del mes"]
    total = max(kpis.get("total_actions", 0), 1)
    rows = [header]
    for item in kpis.get("by_group") or []:
        pct = f"{(item['count'] * 100 / total):.1f}%"
        rows.append([item["label"], item["code"], str(item["count"]), pct])
    if len(rows) == 1:
        rows.append(["—", "—", "0", "0.0%"])
    tbl = Table(rows, colWidths=[2.6 * inch, 1.4 * inch, 1.0 * inch, 1.0 * inch])
    tbl.setStyle(_summary_table_style())
    return tbl


def _table_top_actors(kpis: Dict[str, Any], styles) -> Table:
    header = ["Nombre / Email", "Rol", "Acciones", "% del mes"]
    total = max(kpis.get("total_actions", 0), 1)
    rows = [header]
    for a in kpis.get("top_actors") or []:
        name = (a.get("name") or a.get("email") or "—")[:36]
        role = (a.get("role") or "—").upper()
        pct = f"{(a['count'] * 100 / total):.1f}%"
        rows.append([name, role, str(a["count"]), pct])
    if len(rows) == 1:
        rows.append(["—", "—", "0", "0.0%"])
    tbl = Table(rows, colWidths=[3.0 * inch, 0.9 * inch, 1.0 * inch, 1.0 * inch])
    tbl.setStyle(_summary_table_style())
    return tbl


def _table_anti_fraud(kpis: Dict[str, Any], styles) -> Table:
    header = ["Acción anti-fraude", "Ocurrencias"]
    rows = [header]
    for item in kpis.get("anti_fraud") or []:
        rows.append([item["action"], str(item["count"])])
    if len(rows) == 1:
        rows.append(["Sin señales de fraude este período", "0"])
    tbl = Table(rows, colWidths=[4.4 * inch, 1.6 * inch])
    tbl.setStyle(_summary_table_style())
    return tbl


def _summary_table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])


# ============================================================
# Detailed table
# ============================================================

def _format_audit_ts(value: str) -> str:
    try:
        return datetime.fromisoformat(value or "").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value or "—"


def _format_perms_effective(entry: dict) -> str:
    eff = entry.get("actor_permissions_effective")
    if eff == "all":
        return "admin"
    if eff == "all_staff_default":
        return "staff*"
    if isinstance(eff, list):
        if not eff:
            return "staff*"
        return f"{len(eff)} perm."
    return "legacy"


def _detail_row(e: dict) -> list:
    actor = e.get("actor_name") or e.get("actor_email") or "—"
    return [
        _format_audit_ts(e.get("created_at", "")),
        actor[:28],
        (e.get("actor_role") or "—").upper(),
        _format_perms_effective(e),
        e.get("action", "—"),
        (e.get("entity_id") or "—")[:10],
        (e.get("summary") or "—")[:70],
    ]


def _build_detail_table(entries: List[dict]) -> Table:
    headers = ["Cuándo (UTC)", "Quién", "Rol", "Perms", "Acción", "ID", "Resumen"]
    data = [headers] + [_detail_row(e) for e in entries]
    if len(data) == 1:
        data.append(["—"] * 7)
    col_widths = [1.35*inch, 1.55*inch, 0.6*inch, 0.65*inch, 1.2*inch, 0.85*inch, 3.2*inch]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_PURPLE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#0c0c0c")),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tbl


# ============================================================
# Main entry point
# ============================================================

def _build_styles():
    styles = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle('h1', parent=styles['Heading1'], textColor=TEXT,
                             fontSize=22, leading=24, fontName="Helvetica-Bold", spaceAfter=4),
        "h2": ParagraphStyle('h2', parent=styles['Heading2'], textColor=BRAND_PURPLE,
                             fontSize=11, leading=14, fontName="Helvetica-Bold", spaceBefore=8,
                             spaceAfter=6),
        "label": ParagraphStyle('label', parent=styles['Normal'], textColor=BRAND_PURPLE,
                                fontSize=8, leading=10, fontName="Helvetica-Bold", spaceAfter=2),
        "sub": ParagraphStyle('sub', parent=styles['Normal'], textColor=TEXT_MUTED,
                              fontSize=9, leading=12, spaceAfter=14),
        "kpi_label": ParagraphStyle('kpi_label', parent=styles['Normal'],
                                    fontSize=7, leading=9, fontName="Helvetica-Bold"),
        "kpi_value": ParagraphStyle('kpi_value', parent=styles['Normal'],
                                    fontSize=16, leading=18, fontName="Helvetica-Bold"),
        "hash": ParagraphStyle('hash', parent=styles['Normal'], textColor=TEXT_MUTED,
                               fontSize=7, leading=9, fontName="Courier"),
    }


def generate_monthly_audit_pdf(entries: List[dict], period_label: str,
                                kpis: Dict[str, Any], integrity_hash: str) -> bytes:
    """Render the monthly report PDF. Returns the file bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(LETTER),
        leftMargin=24, rightMargin=24, topMargin=80, bottomMargin=44,
    )
    S = _build_styles()

    story: List[Any] = []
    story.append(Paragraph("/ REPORTE MENSUAL", S["label"]))
    story.append(Paragraph(f"Auditoría · {period_label}", S["h1"]))
    story.append(Paragraph(
        f"Total de acciones registradas en el período: "
        f"<font color='#8B5CF6'><b>{kpis.get('total_actions', 0)}</b></font> · "
        f"Actores distintos: <font color='#8B5CF6'><b>{kpis.get('distinct_actors', 0)}</b></font>",
        S["sub"],
    ))

    # 1. KPI strip
    story.append(_summary_strip(kpis, S))
    story.append(Spacer(1, 12))

    # 2. Two-column: by-group + top actors
    story.append(Paragraph("Acciones por categoría", S["h2"]))
    story.append(KeepTogether(_table_by_group(kpis, S)))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Top actores del período", S["h2"]))
    story.append(KeepTogether(_table_top_actors(kpis, S)))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Señales anti-fraude", S["h2"]))
    story.append(KeepTogether(_table_anti_fraud(kpis, S)))
    story.append(Spacer(1, 6))

    # 3. Detailed page break
    story.append(PageBreak())
    story.append(Paragraph("/ DETALLE CRONOLÓGICO", S["label"]))
    story.append(Paragraph(f"Todas las acciones · {period_label}", S["h1"]))
    story.append(Paragraph(
        "Filas ordenadas de la más reciente a la más antigua. "
        "La columna <b>Perms</b> muestra el alcance efectivo del actor en el momento del evento.",
        S["sub"],
    ))
    story.append(_build_detail_table(entries))
    story.append(Spacer(1, 14))

    # 4. Integrity footer (last thing before doc end)
    story.append(Paragraph("Firma de integridad", S["h2"]))
    story.append(Paragraph(
        "Hash SHA-256 sobre la proyección canónica de todos los eventos del "
        "período (id · timestamp · actor · acción · entidad). Recalculable en "
        "cualquier momento desde el registro de auditoría — si difiere del valor "
        "impreso, alguien modificó filas históricas.",
        S["sub"],
    ))
    story.append(Paragraph(f"<b>Período:</b> {period_label}", S["hash"]))
    story.append(Paragraph(f"<b>Filas incluidas:</b> {len(entries)}", S["hash"]))
    story.append(Paragraph(f"<b>SHA-256:</b> {integrity_hash}", S["hash"]))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
