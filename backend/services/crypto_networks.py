"""iter55.19c — Crypto network ↔ address compatibility.

Rationale: operator wants BingX-style "No coinciden" detection so a client
requesting a USDT withdrawal on BEP20 can NOT paste a TRC20 address (which
would irrecoverably lose the funds).

Supported networks (per operator decision, iter55.19c):
- TRC20 (Tron) — addresses match `T` + 33 base58 chars = 34 total
- BEP20 (BSC)  — addresses match `0x` + 40 hex chars = 42 total (EVM format)

Technical note: BEP20, ERC20, Polygon, Arbitrum and Optimism all share the
EVM address format (`0x` + 40 hex). By the address alone we can only tell if
it *looks* EVM or Tron — we cannot distinguish EVM sub-chains. BingX behaves
the same way: it only flags mismatches across families, not within EVM.
"""
from __future__ import annotations

import re
from typing import Final, List


# Base58 alphabet (excludes 0, O, I, l for legibility)
_TRC20_RE: Final = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
_EVM_RE: Final = re.compile(r"^0x[0-9a-fA-F]{40}$")

# iter55.19h — TX HASH patterns (distinct from address patterns above).
# * TRC20 tx hash: 64 hex characters, NO 0x prefix (Tronscan convention).
# * EVM tx hash:   0x + 64 hex characters (Ethereum/BSC/Polygon convention).
_TRC20_HASH_RE: Final = re.compile(r"^[0-9a-fA-F]{64}$")
_EVM_HASH_RE: Final = re.compile(r"^0x[0-9a-fA-F]{64}$")


SUPPORTED_NETWORKS: List[str] = ["TRC20", "BEP20"]

NETWORK_LABELS = {
    "TRC20": "Tron (TRC20)",
    "BEP20": "BSC (BEP20)",
}

# Human-readable hints shown in the UI + error messages.
NETWORK_PLACEHOLDERS = {
    "TRC20": "T + 33 caracteres alfanuméricos (ej. TJRabc123...)",
    "BEP20": "0x + 40 caracteres hexadecimales (ej. 0xAbCdEf...)",
}


def is_supported_network(network: str) -> bool:
    return network in SUPPORTED_NETWORKS


def detect_family(address: str) -> str:
    """Return the address family: 'tron' | 'evm' | 'unknown'.

    We use family (not exact network) because 0x-addresses are ambiguous
    across EVM chains. Callers should combine this with the client-declared
    network to decide validity.
    """
    if not address:
        return "unknown"
    addr = address.strip()
    if _TRC20_RE.match(addr):
        return "tron"
    if _EVM_RE.match(addr):
        return "evm"
    return "unknown"


_NETWORK_FAMILY = {
    "TRC20": "tron",
    "BEP20": "evm",
}


def is_address_valid_for_network(address: str, network: str) -> bool:
    """Strict predicate — returns True only when the address matches the
    declared network's family. Empty/unknown → False."""
    if not is_supported_network(network):
        return False
    if not address or not address.strip():
        return False
    return detect_family(address) == _NETWORK_FAMILY[network]


def mismatch_reason(address: str, network: str) -> str:
    """Return a human-friendly Spanish reason why the address doesn't match.
    Only meaningful when is_address_valid_for_network(...) == False."""
    if not is_supported_network(network):
        return f"Red '{network}' no soportada — usa {' o '.join(SUPPORTED_NETWORKS)}."
    fam = detect_family(address)
    label = NETWORK_LABELS.get(network, network)
    if fam == "unknown":
        return (
            f"La dirección no tiene el formato de {label}. "
            f"Se espera: {NETWORK_PLACEHOLDERS[network]}."
        )
    # Address is well-formed but belongs to the wrong family.
    fam_label = "Tron" if fam == "tron" else "EVM (BSC/ETH/Polygon…)"
    return (
        f"La dirección parece de la red {fam_label}, pero seleccionaste {label}. "
        f"Revisa la red o pega otra dirección — enviar por la red incorrecta "
        f"puede perder los fondos permanentemente."
    )


# ============================================================
# iter55.19h — TX HASH validation
# ============================================================

# Human-readable formats for the UI + error messages.
TX_HASH_PLACEHOLDERS = {
    "TRC20": "64 caracteres hexadecimales sin 0x (ej. abc123def456...)",
    "BEP20": "0x + 64 caracteres hexadecimales (ej. 0xabc123...)",
}


def detect_hash_family(tx_hash: str) -> str:
    """Return the hash family: 'tron' | 'evm' | 'unknown'."""
    if not tx_hash:
        return "unknown"
    h = tx_hash.strip()
    if _EVM_HASH_RE.match(h):
        return "evm"
    if _TRC20_HASH_RE.match(h):
        return "tron"
    return "unknown"


def is_tx_hash_valid_for_network(tx_hash: str, network: str) -> bool:
    """Strict predicate — True only when the hash matches the declared
    network's family. Empty / unknown / unsupported network → False."""
    if not is_supported_network(network):
        return False
    if not tx_hash or not tx_hash.strip():
        return False
    return detect_hash_family(tx_hash) == _NETWORK_FAMILY[network]


def tx_hash_mismatch_reason(tx_hash: str, network: str) -> str:
    """Spanish diagnosis for an invalid hash + declared network combo."""
    if not is_supported_network(network):
        return f"Red '{network}' no soportada — usa {' o '.join(SUPPORTED_NETWORKS)}."
    fam = detect_hash_family(tx_hash)
    label = NETWORK_LABELS.get(network, network)
    if fam == "unknown":
        return (
            f"El hash no tiene el formato de {label}. "
            f"Se espera: {TX_HASH_PLACEHOLDERS[network]}."
        )
    fam_label = "Tron" if fam == "tron" else "EVM (BSC/ETH/Polygon…)"
    return (
        f"El hash parece de la red {fam_label}, pero el retiro está declarado en {label}. "
        f"Revisa el hash pegado — probablemente lo copiaste del explorer equivocado."
    )
