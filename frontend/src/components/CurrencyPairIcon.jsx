/**
 * iter93 — TradingView-style overlapping currency pair icon.
 *
 * TradingView, Binance, Bybit and Pancake all share the same visual
 * convention for a trading pair: two circular coin logos overlapping
 * by ~50%, the right one slightly stacked above with a subtle
 * background-coloured ring so both silhouettes stay readable. This
 * component packages that convention on top of the existing
 * `CurrencyIcon` so callers just pass `from` + `to` codes.
 *
 * Behaviour:
 * - The pair icon is a horizontal flex row: [ orb A ][ orb B (overlap) ]
 *   followed by an optional monospace label "FROM → TO" (default off,
 *   so the icon can live inside a cell that already has its own text).
 * - Sizes reuse the CurrencyIcon `size` prop (xs/sm/md/lg) so a rate
 *   row can stay compact while an order-detail dialog gets bigger orbs.
 *
 * Usage:
 *   <CurrencyPairIcon from="ZELLE" to="CUP" />                  // icon only
 *   <CurrencyPairIcon from="ZELLE" to="CUP" size="md" showLabel />
 */
import CurrencyIcon from "./CurrencyIcon";

const OVERLAP_BY_SIZE = {
  xs: "-ml-1.5",
  sm: "-ml-2",
  md: "-ml-2.5",
  lg: "-ml-3.5",
};

export default function CurrencyPairIcon({
  from,
  to,
  size = "sm",
  showLabel = false,
  className = "",
  separator = "→",
}) {
  const overlap = OVERLAP_BY_SIZE[size] || OVERLAP_BY_SIZE.sm;
  return (
    <span
      className={`inline-flex items-center gap-2 whitespace-nowrap ${className}`}
      data-testid={`pair-icon-${from}-${to}`}
    >
      <span className="inline-flex items-center">
        {/* First orb — plain */}
        <CurrencyIcon code={from} size={size} />
        {/* Second orb — pulled left with a tight ring in the page BG so
            the two circles stay visually separate even when both are
            similarly coloured. `ring-neutral-950` matches the app's
            dark theme; the ring is invisible on already-dark orbs and
            provides a hairline separator on light ones. */}
        <span
          className={`inline-flex ${overlap} ring-2 ring-neutral-950 rounded-full`}
        >
          <CurrencyIcon code={to} size={size} />
        </span>
      </span>
      {showLabel && (
        <span className="font-mono text-sm">
          {from} <span className="text-neutral-500">{separator}</span> {to}
        </span>
      )}
    </span>
  );
}
