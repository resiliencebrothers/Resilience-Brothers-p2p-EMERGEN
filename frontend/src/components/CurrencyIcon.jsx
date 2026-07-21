/**
 * iter78 / iter80 — CurrencyIcon
 *
 * Compact visual token for a currency code, drawn inline with SVG so it
 * renders instantly and matches the dark theme without external assets.
 *
 * Rendering priority (first match wins):
 *   1. CUSTOM_RENDER — brand-specific artwork (US flag for USD, Zelle Z,
 *      CUP / CUPT peso circles). iter80 addition, matches the reference
 *      assets provided by the product owner.
 *   2. BRAND_STYLE   — crypto + a few branded fiats. Coloured circle with
 *      the ticker glyph.
 *   3. FIAT_GLYPH    — currency-glyph circle with a stable hash-based tone.
 *   4. Fallback      — violet circle with the first letter.
 *
 * Props:
 *   - code:  currency code (required)
 *   - size:  "xs" | "sm" | "md" | "lg"  (default "sm")
 *   - showLabel: boolean — when true renders `<icon> CODE` inline.
 */

const SIZE_MAP = {
  xs: { box: "w-4 h-4",  text: "text-[0.55rem]", px: 16 },
  sm: { box: "w-5 h-5",  text: "text-[0.6rem]",  px: 20 },
  md: { box: "w-7 h-7",  text: "text-xs",        px: 28 },
  lg: { box: "w-10 h-10", text: "text-sm",       px: 40 },
};

// ---------------------------------------------------------------------------
// iter92 — Custom BITMAP logos (PNGs shipped in /public/currency-icons/).
// Some currencies deserve a photographic-quality coin instead of a flat SVG
// (e.g. the operator provided artisanal USD-Efectivo and AED coin renders).
//
// Match strategy (in priority order):
//   1. Exact `AED` code                          → AED coin.
//   2. Code contains DIRHAM or DUBAI              → AED coin (covers custom
//      operator naming like DIRHAM_DUBAI, AED_DUBAI, DUBAI_DIRHAM…).
//   3. Code starts with USDCASH                   → USD Efectivo coin
//      (covers USDCASH_TEST, USDCASH2_TEST, USDCASH27…).
// ---------------------------------------------------------------------------
function resolveImageIcon(code) {
  const up = (code || "").toUpperCase();
  if (!up) return null;
  if (up === "AED") return "/currency-icons/aed.png";
  if (up.includes("DIRHAM") || up.includes("DUBAI")) return "/currency-icons/aed.png";
  if (up.startsWith("USDCASH")) return "/currency-icons/usd-cash.png";
  return null;
}
// Exported for unit tests + future re-use (e.g. showing the coin inline
// in a receipt / PDF preview without mounting the full React component).
export { resolveImageIcon };

// ---------------------------------------------------------------------------
// iter80 — Custom-rendered icons for currencies with strong brand identity.
// Each entry is a function that receives the pixel size and returns the JSX
// to render INSIDE a rounded-full container. This lets us mix SVG artwork
// (US flag) with styled letters (Zelle "Z") uniformly.
// ---------------------------------------------------------------------------
const CUSTOM_RENDER = {
  // Bitcoin — official orange square-rounded token with the classic
  // stylised "₿" (B with cut-through verticals). Rendered as a proper
  // brand mark instead of a generic ₿ glyph on a circle.
  BTC: (px) => (
    <svg viewBox="0 0 32 32" width={px} height={px} aria-hidden="true">
      <circle cx="16" cy="16" r="16" fill="#F7931A" />
      <path
        d="M22.24 14.66c.29-1.93-1.19-2.97-3.21-3.66l.66-2.63-1.6-.4-.64 2.56c-.42-.11-.85-.2-1.29-.3l.65-2.58-1.6-.4-.66 2.63c-.35-.08-.69-.16-1.03-.24v-.01l-2.21-.55-.43 1.7s1.19.27 1.16.29c.65.16.77.59.75.93l-.75 3-.11-.03.11.03-1.06 4.21c-.08.2-.28.5-.75.38.02.02-1.16-.29-1.16-.29l-.79 1.83 2.08.52c.39.1.77.2 1.14.3l-.67 2.66 1.6.4.66-2.64c.44.12.86.23 1.28.33l-.66 2.62 1.6.4.67-2.66c2.72.51 4.77.31 5.63-2.15.7-1.99-.03-3.13-1.46-3.88 1.04-.24 1.83-.93 2.04-2.34zm-3.64 5.12c-.5 1.99-3.83.91-4.91.65l.89-3.54c1.08.27 4.54.8 4.02 2.89zm.5-5.15c-.45 1.8-3.23.89-4.13.66l.8-3.21c.9.22 3.79.65 3.33 2.55z"
        fill="#FFFFFF"
      />
    </svg>
  ),

  // Euro — European Union flag: blue field with a ring of 12 gold stars.
  EUR: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="eur-clip">
          <circle cx="12" cy="12" r="12" />
        </clipPath>
      </defs>
      <g clipPath="url(#eur-clip)">
        <rect width="24" height="24" fill="#003399" />
        {/* 12 gold stars arranged on a ring around the centre. Renders as
            small dots at ≤ 20px and readable ★ characters at md/lg. */}
        {Array.from({ length: 12 }).map((_, i) => {
          const angle = (i / 12) * Math.PI * 2 - Math.PI / 2;
          const cx = 12 + Math.cos(angle) * 7.5;
          const cy = 12 + Math.sin(angle) * 7.5;
          return (
            <text
              key={i}
              x={cx}
              y={cy + 1.4}
              textAnchor="middle"
              fontSize={px >= 24 ? 3.2 : 4.5}
              fill="#FFCC00"
              fontFamily="sans-serif"
              fontWeight="700"
            >
              ★
            </text>
          );
        })}
      </g>
    </svg>
  ),

  // British Pound — Union Jack inside a circle.
  GBP: (px) => (
    <svg viewBox="0 0 60 60" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="gbp-clip">
          <circle cx="30" cy="30" r="30" />
        </clipPath>
      </defs>
      <g clipPath="url(#gbp-clip)">
        <rect width="60" height="60" fill="#012169" />
        {/* White diagonals (St Andrew's cross). */}
        <path d="M0,0 L60,60 M60,0 L0,60" stroke="#FFFFFF" strokeWidth="12" />
        {/* Red diagonals with offset to form the classic Union Jack layout. */}
        <path
          d="M0,0 L60,60 M60,0 L0,60"
          stroke="#C8102E"
          strokeWidth="4"
          clipPath="url(#gbp-clip)"
        />
        {/* White St George's cross (thicker). */}
        <path d="M30,0 V60 M0,30 H60" stroke="#FFFFFF" strokeWidth="16" />
        {/* Red St George's cross on top. */}
        <path d="M30,0 V60 M0,30 H60" stroke="#C8102E" strokeWidth="8" />
      </g>
    </svg>
  ),

  // iter82 — Latin-American fiat flags. All rendered inside a circular
  // clip so they visually match the USD/EUR/GBP style. Each uses a
  // per-code clipPath id so multiple icons can coexist on the same page
  // without SVG id collisions.

  // Mexico — vertical green/white/red tricolor with a stylised "$" mark
  // on the white centre band (skipping the elaborate eagle for legibility
  // at small sizes).
  MXN: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="mxn-clip"><circle cx="12" cy="12" r="12" /></clipPath>
      </defs>
      <g clipPath="url(#mxn-clip)">
        <rect x="0" y="0" width="8" height="24" fill="#006847" />
        <rect x="8" y="0" width="8" height="24" fill="#FFFFFF" />
        <rect x="16" y="0" width="8" height="24" fill="#CE1126" />
        <text
          x="12" y="16" textAnchor="middle"
          fontSize="9" fontWeight="800" fill="#8B5A00"
          fontFamily="system-ui, -apple-system, sans-serif"
        >
          $
        </text>
      </g>
    </svg>
  ),

  // Argentina — horizontal light-blue / white / light-blue with the Sun
  // of May in the centre (simplified radial glyph).
  ARS: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="ars-clip"><circle cx="12" cy="12" r="12" /></clipPath>
      </defs>
      <g clipPath="url(#ars-clip)">
        <rect x="0" y="0" width="24" height="8" fill="#74ACDF" />
        <rect x="0" y="8" width="24" height="8" fill="#FFFFFF" />
        <rect x="0" y="16" width="24" height="8" fill="#74ACDF" />
        {/* Sun of May — 8 rays + central disk. */}
        <g transform="translate(12,12)">
          {Array.from({ length: 8 }).map((_, i) => {
            const a = (i / 8) * Math.PI * 2;
            const x2 = Math.cos(a) * 3.5;
            const y2 = Math.sin(a) * 3.5;
            return (
              <line
                key={i}
                x1="0" y1="0" x2={x2} y2={y2}
                stroke="#F6B40E" strokeWidth="0.9" strokeLinecap="round"
              />
            );
          })}
          <circle r="1.6" fill="#F6B40E" />
        </g>
      </g>
    </svg>
  ),

  // Venezuela — horizontal yellow / blue / red with a small arc of
  // 8 stars on the blue band (approximation of the real 8-star arc).
  VES: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="ves-clip"><circle cx="12" cy="12" r="12" /></clipPath>
      </defs>
      <g clipPath="url(#ves-clip)">
        <rect x="0" y="0" width="24" height="8" fill="#FCE300" />
        <rect x="0" y="8" width="24" height="8" fill="#003893" />
        <rect x="0" y="16" width="24" height="8" fill="#CF142B" />
        {/* Star arc on the blue stripe. */}
        {Array.from({ length: 5 }).map((_, i) => {
          const t = (i - 2) / 5; // -0.4..0.4 across the width
          const cx = 12 + t * 12;
          const cy = 13 - Math.abs(t) * 1.5;
          return (
            <text
              key={i}
              x={cx} y={cy + 1.3} textAnchor="middle"
              fontSize="2.4" fill="#FFFFFF" fontWeight="700"
            >
              ★
            </text>
          );
        })}
      </g>
    </svg>
  ),

  // Colombia — horizontal yellow (top half) / blue (quarter) / red (quarter).
  COP: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="cop-clip"><circle cx="12" cy="12" r="12" /></clipPath>
      </defs>
      <g clipPath="url(#cop-clip)">
        <rect x="0" y="0" width="24" height="12" fill="#FCD116" />
        <rect x="0" y="12" width="24" height="6" fill="#003893" />
        <rect x="0" y="18" width="24" height="6" fill="#CE1126" />
      </g>
    </svg>
  ),

  // Brazil — green field, yellow rhombus, blue disc with a white banner
  // stripe. The starry constellation is dropped for legibility below 40px.
  BRL: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="brl-clip"><circle cx="12" cy="12" r="12" /></clipPath>
      </defs>
      <g clipPath="url(#brl-clip)">
        <rect width="24" height="24" fill="#009C3B" />
        <polygon points="12,3 21,12 12,21 3,12" fill="#FFDF00" />
        <circle cx="12" cy="12" r="4.2" fill="#002776" />
        {/* Simplified equatorial band. */}
        <path
          d="M 8.2 12.2 Q 12 10.5 15.8 12.2"
          stroke="#FFFFFF" strokeWidth="0.7" fill="none"
        />
      </g>
    </svg>
  ),

  // Chile — top half white with a blue square canton (upper-left) that
  // carries a white five-point star; bottom half red.
  CLP: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="clp-clip"><circle cx="12" cy="12" r="12" /></clipPath>
      </defs>
      <g clipPath="url(#clp-clip)">
        <rect x="0" y="0" width="24" height="12" fill="#FFFFFF" />
        <rect x="0" y="12" width="24" height="12" fill="#D52B1E" />
        <rect x="0" y="0" width="12" height="12" fill="#0039A6" />
        <text
          x="6" y="9.2" textAnchor="middle"
          fontSize="8" fill="#FFFFFF" fontWeight="900"
        >
          ★
        </text>
      </g>
    </svg>
  ),

  // Peru — vertical red / white / red stripes.
  PEN: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="pen-clip"><circle cx="12" cy="12" r="12" /></clipPath>
      </defs>
      <g clipPath="url(#pen-clip)">
        <rect x="0" y="0" width="8" height="24" fill="#D91023" />
        <rect x="8" y="0" width="8" height="24" fill="#FFFFFF" />
        <rect x="16" y="0" width="8" height="24" fill="#D91023" />
      </g>
    </svg>
  ),

  // US Dollar — American flag inside a circle (used for "US Dollar" cash
  // entries per the product-owner screenshot).
  USD: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <defs>
        <clipPath id="usd-flag-clip">
          <circle cx="12" cy="12" r="12" />
        </clipPath>
      </defs>
      <g clipPath="url(#usd-flag-clip)">
        <rect width="24" height="24" fill="#B22234" />
        {/* 6 white stripes over the red background — reads as a flag at
            small sizes without cluttering with 13 stripes. */}
        {[3.3, 6.6, 9.9, 13.2, 16.5, 19.8].map((y) => (
          <rect key={y} x="0" y={y} width="24" height="1.65" fill="#FFFFFF" />
        ))}
        {/* Blue canton (upper-left). */}
        <rect x="0" y="0" width="10.5" height="10.5" fill="#3C3B6E" />
        {/* Simplified star field — one central star reads cleanly at 20px. */}
        <text
          x="5.25"
          y="7.9"
          textAnchor="middle"
          fontSize="7"
          fill="#FFFFFF"
          fontWeight="700"
          fontFamily="sans-serif"
        >
          ★
        </text>
      </g>
    </svg>
  ),

  // Zelle — official purple with a bold white "Z".
  ZELLE: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <rect width="24" height="24" rx="6" fill="#6D1ED4" />
      <text
        x="12"
        y="17.5"
        textAnchor="middle"
        fontSize="17"
        fontWeight="900"
        fill="#FFFFFF"
        fontFamily="system-ui, -apple-system, sans-serif"
        fontStyle="italic"
      >
        z
      </text>
    </svg>
  ),

  // CUP Transferencia — green ring with a white core and a green peso "₽".
  // Small transfer-arrow marker in the corner to hint the "transferencia"
  // meaning at md/lg sizes.
  CUPT: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <circle cx="12" cy="12" r="12" fill="#1F7A3A" />
      <circle cx="12" cy="12" r="9.5" fill="#FFFFFF" />
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontSize="14"
        fontWeight="800"
        fill="#1F7A3A"
        fontFamily="system-ui, -apple-system, sans-serif"
      >
        ₽
      </text>
      {/* Corner arrow badge only readable at md/lg. */}
      {px >= 24 && (
        <g transform="translate(15.5,15.5)">
          <circle r="4" fill="#1F7A3A" />
          <path
            d="M -1.8 -0.7 L 1.6 -0.7 M 0.4 -1.8 L 1.6 -0.7 L 0.4 0.4 M 1.8 1.4 L -1.6 1.4 M -0.4 2.5 L -1.6 1.4 L -0.4 0.3"
            stroke="#FFFFFF"
            strokeWidth="0.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </g>
      )}
    </svg>
  ),

  // CUP Efectivo — blue ring with a white core and a blue peso "₽".
  CUP: (px) => (
    <svg viewBox="0 0 24 24" width={px} height={px} aria-hidden="true">
      <circle cx="12" cy="12" r="12" fill="#1E3A8A" />
      <circle cx="12" cy="12" r="9.5" fill="#FFFFFF" />
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fontSize="14"
        fontWeight="800"
        fill="#1E3A8A"
        fontFamily="system-ui, -apple-system, sans-serif"
      >
        ₽
      </text>
    </svg>
  ),
};

// Brand-styled tokens (letter-based). Fallback path for anything not covered
// by CUSTOM_RENDER.
const BRAND_STYLE = {
  USDT:  { bg: "#26A17B", fg: "#FFFFFF", glyph: "₮" },
  USDC:  { bg: "#2775CA", fg: "#FFFFFF", glyph: "USD" },
  ETH:   { bg: "#627EEA", fg: "#FFFFFF", glyph: "Ξ" },
  BNB:   { bg: "#F0B90B", fg: "#1A1730", glyph: "BNB" },
  TRX:   { bg: "#EB0029", fg: "#FFFFFF", glyph: "TRX" },
  SOL:   { bg: "#14F195", fg: "#0E0E10", glyph: "SOL" },
  MATIC: { bg: "#8247E5", fg: "#FFFFFF", glyph: "M" },
  POL:   { bg: "#8247E5", fg: "#FFFFFF", glyph: "POL" },
  DAI:   { bg: "#F5AC37", fg: "#1A1730", glyph: "◈" },
  XRP:   { bg: "#23292F", fg: "#FFFFFF", glyph: "XRP" },
  DOGE:  { bg: "#C2A633", fg: "#FFFFFF", glyph: "Ð" },
  ADA:   { bg: "#0033AD", fg: "#FFFFFF", glyph: "₳" },
};

const FIAT_GLYPH = {
  JPY: "¥",
  CAD: "$", AUD: "$",
};

// Palette used to keep fiat circles visually distinct without being loud.
const FIAT_TONES = [
  "#3B82F6", "#10B981", "#F59E0B", "#EC4899",
  "#8B5CF6", "#14B8A6", "#EF4444", "#6366F1",
];

function stableHash(str) {
  let h = 0;
  for (let i = 0; i < str.length; i += 1) {
    h = (h * 31 + str.charCodeAt(i)) & 0xffffffff;
  }
  return Math.abs(h);
}

function resolveLetterStyle(code) {
  const up = (code || "").toUpperCase();
  if (BRAND_STYLE[up]) return BRAND_STYLE[up];
  if (FIAT_GLYPH[up]) {
    const tone = FIAT_TONES[stableHash(up) % FIAT_TONES.length];
    return { bg: tone, fg: "#FFFFFF", glyph: FIAT_GLYPH[up] };
  }
  const letter = up ? up.charAt(0) : "?";
  return { bg: "#8B5CF6", fg: "#FFFFFF", glyph: letter };
}

export default function CurrencyIcon({ code, size = "sm", showLabel = false, className = "" }) {
  const dims = SIZE_MAP[size] || SIZE_MAP.sm;
  const up = (code || "").toUpperCase();
  let orb;
  // iter92 — bitmap coin logo takes precedence over SVG variants.
  const imgSrc = resolveImageIcon(up);
  if (imgSrc) {
    orb = (
      <span
        className={`inline-flex items-center justify-center overflow-hidden rounded-full shrink-0 ${dims.box}`}
        data-testid={`currency-icon-${up}`}
        aria-label={code}
      >
        <img
          src={imgSrc}
          alt={code}
          loading="lazy"
          className="w-full h-full object-cover"
        />
      </span>
    );
  } else {
    const customRender = CUSTOM_RENDER[up];
    if (customRender) {
    // Custom SVG art — we still wrap it in a rounded container so the
    // artwork is clipped to the same circle shape as the letter tokens.
    orb = (
      <span
        className={`inline-flex items-center justify-center overflow-hidden rounded-full shrink-0 ${dims.box}`}
        data-testid={`currency-icon-${up}`}
        aria-label={code}
      >
        {customRender(dims.px)}
      </span>
    );
  } else {
    const style = resolveLetterStyle(code);
    const glyph = style.glyph.length > 2 ? style.glyph.slice(0, 3) : style.glyph;
    orb = (
      <span
        className={`inline-flex items-center justify-center rounded-full font-bold shrink-0 ${dims.box} ${dims.text}`}
        style={{ backgroundColor: style.bg, color: style.fg, letterSpacing: "-0.02em" }}
        data-testid={`currency-icon-${up || "UNKNOWN"}`}
        aria-label={code}
      >
        {glyph}
      </span>
    );
    }
  }
  if (!showLabel) return orb;
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      {orb}
      <span className="font-mono">{up}</span>
    </span>
  );
}
