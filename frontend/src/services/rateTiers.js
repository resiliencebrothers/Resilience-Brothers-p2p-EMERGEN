// iter143 — Amount-tiered exchange rates (client-side twin of
// backend services/rate_tiers.py). A tier applies when the sent amount
// >= tier.min_amount; the tier with the HIGHEST matching min wins.

export function pickTierFromList(tiers, amount) {
  const list = Array.isArray(tiers) ? tiers : [];
  const amt = Number(amount);
  if (!list.length || !Number.isFinite(amt) || amt <= 0) return null;
  const sorted = [...list].sort((a, b) => Number(b.min_amount) - Number(a.min_amount));
  return sorted.find((t) => amt >= Number(t.min_amount)) || null;
}

export function pickTier(rate, amount) {
  return pickTierFromList(rate?.tiers, amount);
}

// Effective rate for the exchange preview: tier override when it matches,
// base rate_normal / rate_vip otherwise.
export function effectiveClientRate(rate, amount, isVip) {
  if (!rate) return 0;
  const tier = pickTier(rate, amount);
  const tierRate = tier ? Number(isVip ? tier.rate_vip : tier.rate_normal) : 0;
  if (tierRate > 0) return tierRate;
  return Number(isVip ? rate.rate_vip : rate.rate_normal) || 0;
}
