"""TOTP-based 2FA service. RFC 6238 compliant via pyotp.

Secrets are encrypted at rest with Fernet (TOTP_MASTER_KEY in .env).
Recovery codes are bcrypt-hashed before storage.
"""
import os
import io
import base64
import secrets as pysecrets

import bcrypt
import pyotp
import qrcode
from cryptography.fernet import Fernet


ISSUER = "Resilience Brothers"
TOTP_DIGITS = 6
TOTP_INTERVAL = 30
TOTP_VALID_WINDOW = 1  # ±1 step (≈ ±30s) for clock drift tolerance


def _get_fernet() -> Fernet:
    key = os.environ.get("TOTP_MASTER_KEY")
    if not key:
        raise RuntimeError("TOTP_MASTER_KEY not configured")
    return Fernet(key.encode())


def generate_secret() -> str:
    """Generate a fresh base32 TOTP secret (160-bit)."""
    return pyotp.random_base32()


def encrypt_secret(plain_secret: str) -> str:
    """Encrypt a base32 TOTP secret for at-rest storage."""
    return _get_fernet().encrypt(plain_secret.encode()).decode()


def decrypt_secret(cipher: str) -> str:
    return _get_fernet().decrypt(cipher.encode()).decode()


def provisioning_uri(secret: str, email: str) -> str:
    """otpauth:// URI to feed into the QR or paste manually."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_data_url(uri: str) -> str:
    """Return data:image/png;base64,... for direct <img src=> embedding."""
    img = qrcode.make(uri, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_totp(secret: str, code: str) -> bool:
    """Validate a 6-digit TOTP code against the user's secret."""
    if not code or not code.isdigit() or len(code) != TOTP_DIGITS:
        return False
    return pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL).verify(
        code, valid_window=TOTP_VALID_WINDOW
    )


def generate_recovery_codes(n: int = 10) -> tuple[list[str], list[str]]:
    """Return (plain_codes_for_display, bcrypt_hashes_for_storage)."""
    plain = []
    hashed = []
    for _ in range(n):
        # 10-char alphanumeric, grouped as XXXXX-XXXXX for readability
        raw = pysecrets.token_hex(5).upper()  # 10 chars
        code = f"{raw[:5]}-{raw[5:]}"
        plain.append(code)
        hashed.append(bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode())
    return plain, hashed


def consume_recovery_code(stored_hashes: list[str], submitted: str) -> tuple[bool, list[str]]:
    """If `submitted` matches one of the stored bcrypt hashes, return (True, remaining_hashes).
    Otherwise (False, unchanged_hashes). Caller persists `remaining_hashes` back.
    """
    if not submitted:
        return False, stored_hashes
    normalized = submitted.strip().upper().replace(" ", "")
    # Allow input without hyphen
    if "-" not in normalized and len(normalized) == 10:
        normalized = f"{normalized[:5]}-{normalized[5:]}"
    remaining: list[str] = []
    matched = False
    for h in stored_hashes:
        if not matched and bcrypt.checkpw(normalized.encode(), h.encode()):
            matched = True
            continue  # consume this code (don't re-add)
        remaining.append(h)
    return matched, remaining
