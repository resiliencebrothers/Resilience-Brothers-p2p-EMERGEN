"""iter158 — Server-side sanity validation of bank-transfer withdrawal
details. Mirrors the client-side rules in
frontend/src/services/delivery_validators.js so the API cannot be bypassed
with fake account numbers (e.g. "11111111111")."""
import re
from typing import Optional

_ASC = "01234567890123456789"
_DESC = _ASC[::-1]


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _looks_dummy(digits: str) -> bool:
    """Repeated digits ("1111…") or perfect sequences ("1234…") aren't real."""
    if not digits:
        return True
    if len(set(digits)) <= 2:
        return True
    return digits in _ASC or digits in _DESC


def validate_transfer_details(currency: str, details: str) -> Optional[str]:
    """Return an error message when the details clearly are NOT a real
    account for the currency's banking rail; None when acceptable."""
    code = (currency or "").upper()
    text = (details or "").strip()
    d = _digits(text)
    has_email = re.search(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}", text) is not None

    if code.startswith("CUP") or code == "MLC":
        if len(d) != 16:
            return (
                f"La tarjeta bancaria cubana debe tener 16 dígitos "
                f"(detectados: {len(d)}). Ej: 9235 9598 7274 4356."
            )
        if _looks_dummy(d):
            return ("El número de tarjeta no parece real (dígitos repetidos "
                    "o en secuencia). Verifícalo antes de enviar.")
        return None

    if code == "MXN":
        if len(d) != 18:
            return f"La CLABE mexicana debe tener 18 dígitos (detectados: {len(d)})."
        if _looks_dummy(d):
            return "La CLABE no parece real (dígitos repetidos o en secuencia)."
        return None

    if code == "EUR":
        if not re.search(r"[A-Za-z]{2}\d{2}[A-Za-z0-9]{10,30}", text.replace(" ", "")):
            return ("Indica un IBAN válido (2 letras de país + dígitos). "
                    "Ej: ES91 2100 0418 4502 0005 1332.")
        return None

    if code == "BRL":
        is_uuid = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            text, re.I,
        )
        is_phone = "+55" in text and len(d) >= 10
        if has_email or is_uuid or is_phone or len(d) in (11, 14):
            return None
        return ("Indica una chave PIX válida: CPF (11 dígitos), CNPJ (14), "
                "email, teléfono (+55…) o chave aleatoria.")

    if code.startswith("USD"):
        if has_email:
            return None
        if 10 <= len(d) <= 22 and not _looks_dummy(d):
            return None
        return ("Indica un email/teléfono de Zelle o routing (9 dígitos) + "
                "número de cuenta.")

    # Generic fallback for other currencies: require something account-like.
    if has_email:
        return None
    if len(d) < 8:
        return ("Los detalles deben incluir el número de cuenta/tarjeta de "
                "destino (mínimo 8 dígitos) o un email.")
    if _looks_dummy(d):
        return ("El número de cuenta no parece real (dígitos repetidos o en "
                "secuencia). Verifícalo antes de enviar.")
    return None
