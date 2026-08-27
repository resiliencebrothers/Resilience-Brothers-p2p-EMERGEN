"""iter167 — Bank statement parsing & normalization for reconciliation.

Priority order (spec §2): structured formats (CSV/XLS/XLSX) parse locally
with heuristic column mapping; digital-text PDFs extract text via PyMuPDF and
structure it with the LLM; scanned PDFs go straight to Gemini as a file
attachment (OCR). Architecture leaves room for OFX/QFX/CAMT.053/MT940 later
(add a branch in `parse_statement`).
"""
import csv
import hashlib
import io
import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0.0"

SUPPORTED_EXTENSIONS = {"csv", "xls", "xlsx", "pdf"}

# --- column synonyms for heuristic CSV/XLSX mapping -------------------------
_COLS = {
    "date": ["date", "fecha", "transaction date", "posting date", "post date",
             "fecha operacion", "fecha operación", "f. operacion", "f.valor",
             "fecha valor", "value date", "booking date", "dia", "día"],
    "amount": ["amount", "importe", "monto", "cantidad", "valor", "amount usd"],
    "credit": ["credit", "abono", "abonos", "haber", "deposit", "deposits",
               "ingreso", "ingresos", "credit amount"],
    "debit": ["debit", "cargo", "cargos", "debe", "withdrawal", "withdrawals",
              "retiro", "egreso", "debit amount"],
    "description": ["description", "descripcion", "descripción", "concepto",
                    "concept", "detail", "details", "detalle", "memo",
                    "narrative", "transaction", "movimiento"],
    "sender": ["sender", "remitente", "ordenante", "from", "payer", "name",
               "nombre", "sender name", "originator", "emisor"],
    "beneficiary": ["beneficiary", "beneficiario", "to", "payee", "receptor"],
    "reference": ["reference", "referencia", "ref", "ref.", "confirmation",
                  "confirmation number", "transaction id", "trace number",
                  "id", "numero", "número", "check or slip #"],
    "balance": ["balance", "saldo", "running balance", "balance posterior",
                "saldo posterior", "ending balance"],
    "time": ["time", "hora"],
}

_METHOD_KEYWORDS = [
    ("zelle", "Zelle"), ("ach", "ACH"), ("wire", "Wire"),
    ("sepa instant", "SEPA Instant"), ("sepa", "SEPA"), ("bizum", "Bizum"),
    ("cash deposit", "Cash Deposit"), ("bank deposit", "Bank Deposit"),
    ("deposito en efectivo", "Cash Deposit"), ("transferencia inmediata", "SEPA Instant"),
    ("transferencia internacional", "Transferencia internacional"),
    ("transferencia", "Transferencia bancaria"), ("transfer", "Transferencia bancaria"),
    ("spei", "SPEI"), ("pix", "PIX"), ("ted", "TED"), ("doc", "DOC"),
]


def _norm(s: Any) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def detect_payment_method(text: str) -> str:
    t = _norm(text)
    for kw, label in _METHOD_KEYWORDS:
        if kw in t:
            return label
    return "Otros"


def parse_amount(raw: Any) -> Optional[float]:
    """Handles '1,234.56', '1.234,56', '$ 1234.56', '(123.45)' negatives."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.,\-]", "", s.strip("() "))
    if not s or s in ("-", ".", ","):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):   # 1.234,56 (EU)
            s = s.replace(".", "").replace(",", ".")
        else:                              # 1,234.56 (US)
            s = s.replace(",", "")
    elif "," in s:
        # single comma: decimal if 1-2 digits after, else thousands
        frac = s.split(",")[-1]
        s = s.replace(",", ".") if len(frac) <= 2 else s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -abs(v) if neg else v


_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
                 "%d/%m/%y", "%m/%d/%y", "%Y/%m/%d", "%d.%m.%Y", "%b %d, %Y",
                 "%d %b %Y", "%B %d, %Y"]


def parse_date(raw: Any, dayfirst: bool = False) -> Optional[str]:
    """Returns ISO date (YYYY-MM-DD) or None."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    s = str(raw).strip()[:30]
    if not s:
        return None
    fmts = list(_DATE_FORMATS)
    if dayfirst:  # prioritise dd/mm for EU banks
        fmts.sort(key=lambda f: 0 if f.startswith("%d") else 1)
    for f in fmts:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    try:
        from dateutil import parser as duparser
        return duparser.parse(s, dayfirst=dayfirst).date().isoformat()
    except Exception:
        return None


def fingerprint(bank_account_id: str, date: str, amount: float, currency: str,
                ref: str, sender: str) -> str:
    base = "|".join([
        str(bank_account_id), str(date or ""), f"{float(amount or 0):.2f}",
        str(currency or "").upper(), _norm(ref)[:80], _norm(sender)[:60],
    ])
    return hashlib.sha256(base.encode()).hexdigest()


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Row mapping (CSV / XLSX share this)
# ---------------------------------------------------------------------------
def _map_headers(headers: List[str]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    normed = [_norm(h) for h in headers]
    for field, synonyms in _COLS.items():
        for i, h in enumerate(normed):
            if not h or i in mapping.values():
                continue
            if h in synonyms or any(h == _norm(x) for x in synonyms):
                mapping[field] = i
                break
        if field not in mapping:  # substring pass
            for i, h in enumerate(normed):
                if not h or i in mapping.values():
                    continue
                if any(syn in h for syn in synonyms if len(syn) > 3):
                    mapping[field] = i
                    break
    return mapping


def _rows_to_transactions(headers: List[str], rows: List[List[Any]],
                          dayfirst: bool) -> Tuple[List[Dict], int]:
    mapping = _map_headers(headers)
    if "date" not in mapping or not (
            "amount" in mapping or "credit" in mapping or "debit" in mapping):
        return [], -1  # signal: heuristic mapping failed → LLM fallback
    txs, errors = [], 0
    for row in rows:
        try:
            def cell(field: str) -> Any:
                idx = mapping.get(field)
                return row[idx] if idx is not None and idx < len(row) else None
            date = parse_date(cell("date"), dayfirst=dayfirst)
            amount, direction = None, None
            if "amount" in mapping:
                amount = parse_amount(cell("amount"))
                if amount is not None:
                    direction = "credit" if amount >= 0 else "debit"
                    amount = abs(amount)
            if amount is None and "credit" in mapping:
                c = parse_amount(cell("credit"))
                if c:
                    amount, direction = abs(c), "credit"
            if amount is None and "debit" in mapping:
                d = parse_amount(cell("debit"))
                if d:
                    amount, direction = abs(d), "debit"
            if not date or amount is None or amount == 0:
                if any(str(c or "").strip() for c in row):
                    errors += 1
                continue
            desc = str(cell("description") or "").strip()
            txs.append({
                "transaction_date": date,
                "time": str(cell("time") or "").strip() or None,
                "amount": round(amount, 2),
                "direction": direction or "credit",
                "sender_name": str(cell("sender") or "").strip() or None,
                "beneficiary_name": str(cell("beneficiary") or "").strip() or None,
                "description": desc or None,
                "reference": str(cell("reference") or "").strip() or None,
                "balance_after": parse_amount(cell("balance")),
                "payment_method": detect_payment_method(
                    " ".join(filter(None, [desc, str(cell("reference") or "")]))),
                "raw": {headers[i]: str(row[i]) for i in range(min(len(headers), len(row)))
                        if str(row[i] or "").strip()},
            })
        except Exception as e:
            logger.warning(f"row parse error: {e}")
            errors += 1
    return txs, errors


def parse_csv(data: bytes, dayfirst: bool) -> Tuple[List[Dict], int, str]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    all_rows = [r for r in reader if any(str(c or "").strip() for c in r)]
    if not all_rows:
        return [], 0, "empty"
    # header row = first row where mapping resolves; some banks prepend titles
    for idx in range(min(6, len(all_rows))):
        headers = [str(c) for c in all_rows[idx]]
        txs, errors = _rows_to_transactions(headers, all_rows[idx + 1:], dayfirst)
        if errors != -1:
            return txs, errors, "csv"
    return [], -1, "csv_unmapped"


def parse_xlsx(data: bytes, dayfirst: bool, ext: str) -> Tuple[List[Dict], int, str]:
    import pandas as pd
    engine = "xlrd" if ext == "xls" else "openpyxl"
    df = pd.read_excel(io.BytesIO(data), engine=engine, header=None, dtype=object)
    all_rows = [[("" if pd.isna(c) else c) for c in row]
                for row in df.values.tolist()]
    all_rows = [r for r in all_rows if any(str(c or "").strip() for c in r)]
    if not all_rows:
        return [], 0, "empty"
    for idx in range(min(6, len(all_rows))):
        headers = [str(c) for c in all_rows[idx]]
        txs, errors = _rows_to_transactions(headers, all_rows[idx + 1:], dayfirst)
        if errors != -1:
            return txs, errors, ext
    return [], -1, f"{ext}_unmapped"


def pdf_extract_text(data: bytes) -> str:
    import fitz
    text_parts = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text_parts.append(page.get_text())
    return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# LLM extraction (Emergent universal key)
# ---------------------------------------------------------------------------
_LLM_SYSTEM = (
    "You are a bank statement data extractor for a payments reconciliation "
    "system. Extract EVERY transaction row you can find and return ONLY a "
    "JSON array (no markdown, no commentary). Each element must have exactly "
    "these keys: transaction_date (YYYY-MM-DD), time (HH:MM or null), amount "
    "(positive number), direction ('credit' if money came IN to the account, "
    "'debit' if it went out), sender_name (string or null), beneficiary_name "
    "(string or null), description (string or null), reference (transaction "
    "id / confirmation / trace number, string or null), balance_after "
    "(number or null), payment_method (one of: Zelle, ACH, Wire, SEPA, "
    "SEPA Instant, Bizum, SPEI, PIX, Transferencia bancaria, "
    "Transferencia internacional, Cash Deposit, Bank Deposit, Otros). "
    "Dates in Spanish statements are usually day-first. If a value is "
    "unknown use null. Some documents (e.g. Zelle activity registries) have "
    "NO date column at all — in that case set transaction_date to null but "
    "STILL extract every row. Words like ACREDITADO, RECIBIDO, DEPOSITO, "
    "ABONO mean the money came in (direction credit). Never invent "
    "transactions."
)


def _parse_llm_json(raw: str) -> List[Dict]:
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("LLM response has no JSON array")
    items = json.loads(s[start:end + 1])
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        amount = parse_amount(it.get("amount"))
        date = parse_date(it.get("transaction_date"))
        # iter187 — rows without a date are valid (e.g. Zelle registries with
        # no date column); the matcher simply skips date scoring for them.
        if amount is None or amount <= 0:
            continue
        direction = it.get("direction")
        out.append({
            "transaction_date": date,
            "time": it.get("time") or None,
            "amount": round(abs(amount), 2),
            "direction": "debit" if direction == "debit" else "credit",
            "sender_name": (it.get("sender_name") or None),
            "beneficiary_name": (it.get("beneficiary_name") or None),
            "description": (it.get("description") or None),
            "reference": (str(it.get("reference")) if it.get("reference") else None),
            "balance_after": parse_amount(it.get("balance_after")),
            "payment_method": it.get("payment_method") or detect_payment_method(
                str(it.get("description") or "")),
            "row_index": i,
            "raw": {"source": "llm", "row": i},
        })
    return out


async def llm_extract_from_text(text: str) -> List[Dict]:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    import uuid
    chat = (LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"],
                    session_id=f"recon-{uuid.uuid4().hex[:10]}",
                    system_message=_LLM_SYSTEM)
            .with_model("gemini", "gemini-3-flash-preview"))
    resp = await chat.send_message(UserMessage(
        text="Extract all transactions from this bank statement text:\n\n" + text[:60000]))
    return _parse_llm_json(str(resp))


async def llm_extract_from_pdf(file_path: str) -> List[Dict]:
    """Scanned PDFs — Gemini reads the file directly (built-in OCR)."""
    from emergentintegrations.llm.chat import (LlmChat, UserMessage,
                                               FileContentWithMimeType)
    import uuid
    chat = (LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"],
                    session_id=f"recon-{uuid.uuid4().hex[:10]}",
                    system_message=_LLM_SYSTEM)
            .with_model("gemini", "gemini-3-flash-preview"))
    pdf = FileContentWithMimeType(file_path=file_path, mime_type="application/pdf")
    resp = await chat.send_message(UserMessage(
        text="Extract all transactions from this bank statement.",
        file_contents=[pdf]))
    return _parse_llm_json(str(resp))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def parse_statement(data: bytes, ext: str, dayfirst: bool,
                          tmp_dir: str = "/tmp") -> Tuple[List[Dict], int, str]:
    """Returns (transactions, error_count, parse_mode)."""
    ext = ext.lower().lstrip(".")
    if ext == "csv":
        txs, errors, mode = parse_csv(data, dayfirst)
        if errors == -1:  # unmapped columns → LLM fallback on raw text
            txs = await llm_extract_from_text(data.decode("utf-8-sig", errors="replace"))
            return txs, 0, "csv_llm"
        return txs, errors, mode
    if ext in ("xls", "xlsx"):
        txs, errors, mode = parse_xlsx(data, dayfirst, ext)
        if errors == -1:
            import pandas as pd
            engine = "xlrd" if ext == "xls" else "openpyxl"
            df = pd.read_excel(io.BytesIO(data), engine=engine, header=None, dtype=object)
            txs = await llm_extract_from_text(df.to_csv(index=False))
            return txs, 0, f"{ext}_llm"
        return txs, errors, mode
    if ext == "pdf":
        text = pdf_extract_text(data)
        if len(text.strip()) >= 120:
            txs = await llm_extract_from_text(text)
            # iter186 — a PDF can contain >120 chars of boilerplate (headers,
            # footers) while the actual rows are scanned images. If the text
            # path yields nothing, retry with file-attachment OCR.
            if txs:
                return txs, 0, "pdf_text_llm"
        # scanned → file attachment OCR
        import uuid as _uuid
        tmp_path = os.path.join(tmp_dir, f"recon_{_uuid.uuid4().hex}.pdf")
        with open(tmp_path, "wb") as f:
            f.write(data)
        try:
            txs = await llm_extract_from_pdf(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return txs, 0, "pdf_ocr_llm"
    raise ValueError(f"Formato no soportado: .{ext}")
