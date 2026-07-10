/**
 * iter55.19f — Block-explorer URL builder.
 *
 * Given a network code (TRC20 / BEP20 / …) and a tx hash, returns the URL
 * that surfaces that transaction in the canonical public explorer for that
 * chain. Returns `null` if the network is unsupported or the hash is empty
 * (so callers can render `null` gracefully instead of broken links).
 *
 * Kept in sync with backend `services/crypto_networks.py` (TRC20 + BEP20 are
 * the operator-supported networks). Extra network keys are included so the
 * function stays useful for legacy rows detected via `extractCryptoNetwork`.
 */
const EXPLORER_URLS = {
  TRC20:   (h) => `https://tronscan.org/#/transaction/${h}`,
  BEP20:   (h) => `https://bscscan.com/tx/${h}`,
  ERC20:   (h) => `https://etherscan.io/tx/${h}`,
  POLYGON: (h) => `https://polygonscan.com/tx/${h}`,
  SOLANA:  (h) => `https://solscan.io/tx/${h}`,
  BTC:     (h) => `https://mempool.space/tx/${h}`,
};

const EXPLORER_LABELS = {
  TRC20:   "Tronscan",
  BEP20:   "BscScan",
  ERC20:   "Etherscan",
  POLYGON: "Polygonscan",
  SOLANA:  "Solscan",
  BTC:     "Mempool",
};

export function buildExplorerUrl(network, txHash) {
  if (!network || !txHash) return null;
  const key = String(network).trim().toUpperCase();
  const builder = EXPLORER_URLS[key];
  if (!builder) return null;
  const hash = String(txHash).trim();
  if (!hash) return null;
  return builder(hash);
}

export function explorerLabel(network) {
  if (!network) return "Explorer";
  const key = String(network).trim().toUpperCase();
  return EXPLORER_LABELS[key] || "Explorer";
}
