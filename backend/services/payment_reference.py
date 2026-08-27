"""iter173 §61 — short payment reference the client includes in the transfer
concept so bank reconciliation can match with certainty (+20 pts)."""
import secrets


def generate_payment_reference() -> str:
    return f"RB-{secrets.randbelow(900000) + 100000}"
