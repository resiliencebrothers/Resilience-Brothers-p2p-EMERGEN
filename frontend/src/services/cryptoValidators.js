/**
 * iter55.19h — Crypto network validation helpers (client-side twins of
 * backend `services/crypto_networks.py`). Kept in sync intentionally with 2
 * supported networks (TRC20 + BEP20) — extending means updating both files.
 */

// Address patterns
const TRC20_ADDR_RE = /^T[1-9A-HJ-NP-Za-km-z]{33}$/;
const EVM_ADDR_RE = /^0x[0-9a-fA-F]{40}$/;

// TX hash patterns
const TRC20_HASH_RE = /^[0-9a-fA-F]{64}$/;
const EVM_HASH_RE = /^0x[0-9a-fA-F]{64}$/;


export const CRYPTO_NETWORKS = [
  { value: "TRC20", label: "Tron (TRC20)",
    addressPlaceholder: "T + 33 caracteres alfanuméricos (ej. TJRabc123...)",
    hashPlaceholder: "64 caracteres hexadecimales sin 0x (ej. abc123...)" },
  { value: "BEP20", label: "BSC (BEP20)",
    addressPlaceholder: "0x + 40 caracteres hexadecimales (ej. 0xAbCdEf...)",
    hashPlaceholder: "0x + 64 caracteres hexadecimales (ej. 0xabc123...)" },
];


export function detectAddressFamily(addr) {
  if (!addr) return "unknown";
  const a = addr.trim();
  if (TRC20_ADDR_RE.test(a)) return "tron";
  if (EVM_ADDR_RE.test(a)) return "evm";
  return "unknown";
}


export function validateCryptoAddress(addr, network) {
  const fam = detectAddressFamily(addr);
  if (network === "TRC20") return fam === "tron";
  if (network === "BEP20") return fam === "evm";
  return false;
}


export function detectHashFamily(hash) {
  if (!hash) return "unknown";
  const h = hash.trim();
  // EVM regex first because it's more specific (has 0x prefix)
  if (EVM_HASH_RE.test(h)) return "evm";
  if (TRC20_HASH_RE.test(h)) return "tron";
  return "unknown";
}


export function validateCryptoHash(hash, network) {
  const fam = detectHashFamily(hash);
  if (network === "TRC20") return fam === "tron";
  if (network === "BEP20") return fam === "evm";
  return false;
}


export function findNetwork(code) {
  return CRYPTO_NETWORKS.find((n) => n.value === code) || CRYPTO_NETWORKS[0];
}
